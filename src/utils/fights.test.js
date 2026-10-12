import assert from "node:assert/strict";
import test from "node:test";

import { dedupeEventFights, fightMatchupKey } from "./fights.js";

function fight(overrides = {}) {
  return {
    fight_id: 10,
    fight_order: 1,
    fight_status: "scheduled",
    fighter_a_id: 1,
    fighter_b_id: 2,
    fighter_a: { full_name: "José Silva" },
    fighter_b: { full_name: "John Smith" },
    ...overrides,
  };
}

test("matchup identity ignores fighter order, accents, and duplicate fighter ids", () => {
  assert.equal(
    fightMatchupKey(fight()),
    fightMatchupKey(fight({
      fight_id: 99,
      fighter_a_id: 88,
      fighter_b_id: 77,
      fighter_a: { full_name: "JohnSmith" },
      fighter_b: { full_name: "Jose Silva" },
    }))
  );
});

test("event cards show one active row for a duplicated matchup", () => {
  const original = fight({ fight_id: 10 });
  const duplicate = fight({ fight_id: 91, fighter_a_id: 77, fighter_b_id: 88 });
  const unique = fight({
    fight_id: 12,
    fight_order: 2,
    fighter_a: { full_name: "Different Fighter" },
    fighter_b: { full_name: "Another Fighter" },
  });

  assert.deepEqual(
    dedupeEventFights([duplicate, unique, original]).map((row) => row.fight_id),
    [10, 12]
  );
});

test("active rebooked row wins over a cancelled duplicate", () => {
  const cancelled = fight({ fight_id: 4, fight_status: "cancelled" });
  const active = fight({ fight_id: 20, fight_status: "scheduled" });
  assert.equal(dedupeEventFights([cancelled, active])[0].fight_id, 20);
});
