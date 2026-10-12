import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { after, before, beforeEach, test } from "node:test";
import { PGlite } from "@electric-sql/pglite";

// Real PostgreSQL semantics in an isolated in-memory engine. This test never
// connects to Supabase or reads any user credentials.
let database;
let migration;

before(async () => {
  database = new PGlite();
  await database.exec(`
    create table public.fights (
      fight_id bigint primary key, event_id bigint not null,
      fighter_a_id bigint not null, fighter_b_id bigint not null,
      winner_id bigint, fight_status text, fight_order integer
    );
    create table public.fight_research (
      fight_id bigint references public.fights(fight_id), bet_side text,
      bet_price integer, stake_units numeric, user_lean text
    );
    create table public.bet_legs (
      fight_id bigint references public.fights(fight_id), bet_side text, leg_price integer
    );
  `);
  migration = await readFile(new URL("../migrations/202610120031_protect_fight_identity.sql", import.meta.url), "utf8");
  await database.exec(migration);
});

beforeEach(async () => {
  await database.exec(`
    truncate public.fights, public.fight_research, public.bet_legs;
    insert into public.fights values (100, 5, 11, 12, null, 'scheduled', 1);
    insert into public.fight_research values (100, 'fighter_a', -120, 1, 'fighter_b');
    insert into public.bet_legs values (100, 'fighter_b', 110);
  `);
});

after(async () => { await database?.close(); });

async function selections() {
  return (await database.query(`
    select 'single' as ticket,
      case r.bet_side when 'fighter_a' then f.fighter_a_id else f.fighter_b_id end as selection,
      f.winner_id, r.bet_price as accepted_price
    from public.fight_research r join public.fights f using (fight_id)
    union all
    select 'parlay',
      case l.bet_side when 'fighter_a' then f.fighter_a_id else f.fighter_b_id end,
      f.winner_id, l.leg_price
    from public.bet_legs l join public.fights f using (fight_id)
    order by ticket
  `)).rows;
}

test("a provider reversal keeps accepted singles, parlay legs and winner identities", async () => {
  await database.exec(`update public.fights set fighter_a_id=12, fighter_b_id=11,
    winner_id=12, fight_status='completed', fight_order=3 where fight_id=100`);
  const result = await selections();
  assert.deepEqual(result, [
    { ticket: "parlay", selection: 12, winner_id: 12, accepted_price: 110 },
    { ticket: "single", selection: 11, winner_id: 12, accepted_price: -120 },
  ]);
});

test("a legacy upsert cannot reverse stored sides", async () => {
  await database.exec(`insert into public.fights (fight_id,event_id,fighter_a_id,fighter_b_id,fight_order)
    values (100,5,12,11,4) on conflict (fight_id) do update set
    fighter_a_id=excluded.fighter_a_id, fighter_b_id=excluded.fighter_b_id, fight_order=excluded.fight_order`);
  assert.deepEqual((await database.query("select fighter_a_id,fighter_b_id,fight_order from public.fights")).rows,
    [{ fighter_a_id: 11, fighter_b_id: 12, fight_order: 4 }]);
});

for (const [label, change] of [
  ["replacement", "fighter_b_id=13"],
  ["rebooking", "event_id=6"],
  ["primary key change", "fight_id=101"],
]) {
  test(`${label} is refused and existing tickets remain unchanged`, async () => {
    const original = await selections();
    await assert.rejects(database.exec(`update public.fights set ${change} where fight_id=100`),
      (error) => error.code === "23514");
    assert.deepEqual(await selections(), original);
  });
}

test("normal metadata updates and new fight insertion remain available", async () => {
  await database.exec(`update public.fights set fight_order=2 where fight_id=100;
    insert into public.fights values (101,6,13,12,null,'scheduled',1)`);
  assert.deepEqual((await database.query("select fight_id,fighter_a_id,fighter_b_id,fight_order from public.fights order by fight_id")).rows, [
    { fight_id: 100, fighter_a_id: 11, fighter_b_id: 12, fight_order: 2 },
    { fight_id: 101, fighter_a_id: 13, fighter_b_id: 12, fight_order: 1 },
  ]);
});

test("migration is repeatable without rewriting historical bets or fights", async () => {
  const before = await selections();
  await database.exec(migration);
  await database.exec(migration);
  assert.deepEqual(await selections(), before);
  assert.equal((await database.query(`select count(*)::int as count from pg_trigger
    where tgname='protect_mma_fight_identity' and not tgisinternal`)).rows[0].count, 1);
});

test("an invalid identity update rolls back the surrounding transaction", async () => {
  await database.exec("begin; update public.fights set fight_order=9 where fight_id=100");
  await assert.rejects(database.exec("update public.fights set fighter_a_id=13 where fight_id=100"));
  await database.exec("rollback");
  assert.equal((await database.query("select fight_order from public.fights where fight_id=100")).rows[0].fight_order, 1);
});

test("the optional rollback removes only the guard and can be reapplied", async () => {
  const original = await selections();
  const rollback = await readFile(new URL("../rollback/202610120031_protect_fight_identity.sql", import.meta.url), "utf8");
  await database.exec(rollback);
  assert.deepEqual(await selections(), original);
  assert.equal((await database.query(`select count(*)::int as count from pg_trigger
    where tgname='protect_mma_fight_identity' and not tgisinternal`)).rows[0].count, 0);
  await database.exec(migration);
  await database.exec("update public.fights set fighter_a_id=12,fighter_b_id=11 where fight_id=100");
  assert.deepEqual(await selections(), original);
});
