-- One-time cleanup authorized by the user after PFL fix 3 imported 11 results.
-- Run this entire file in the MMA project's Supabase SQL Editor as postgres.
-- It removes only the omitted scheduled fight #9541, never fight #9540.
-- Research or bet legs stop the cleanup. Removed rows get a private backup.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create schema if not exists mma_recovery;
revoke all on schema mma_recovery from public, anon, authenticated;
create table if not exists mma_recovery.fight_cleanups (
  cleanup_key text primary key,
  fight_id bigint not null,
  created_at timestamptz not null default now(),
  restored_at timestamptz,
  payload jsonb not null
);
revoke all on mma_recovery.fight_cleanups from public, anon, authenticated;

do $cleanup$
declare
  target public.fights;
  event_row public.events;
  snapshot jsonb;
  related jsonb;
  table_name text;
  completed_count integer;
  official_count integer;
  dependency record;
  has_dependency boolean;
begin
  -- Coordinate with the existing importer and Discord snapshot lock.
  perform public.mma_check_import_lease(null, null);
  select * into target from public.fights where fight_id = 9541 for update;
  if not found then
    if exists (select 1 from mma_recovery.fight_cleanups
               where cleanup_key = 'pfl-morocco-9541' and restored_at is null) then
      return; -- Repeated cleanup is a no-op and never replaces the backup.
    end if;
    raise exception 'Fight #9541 was not found. No fight data was changed.';
  end if;
  select * into strict event_row from public.events
    where event_id = target.event_id for update;
  if event_row.event_name is distinct from 'PFL Africa Morocco'
     or event_row.event_date is distinct from date '2026-10-10'
     or not exists (select 1 from public.promotions
                    where promotion_id = event_row.promotion_id
                      and lower(name) in ('pfl', 'professional fighters league')) then
    raise exception 'Fight #9541 is not the reported PFL Morocco event. Nothing was deleted.';
  end if;
  if coalesce(target.fight_status, '') not in ('scheduled', 'upcoming')
     or target.winner_id is not null or target.result_confirmed_at is not null then
    raise exception 'Fight #9541 has a result or changed status. Nothing was deleted.';
  end if;
  perform 1 from public.fight_research where fight_id = 9541 for update;
  if found then
    raise exception 'Fight #9541 has saved research or a single-bet record. Nothing was deleted.';
  end if;
  if exists (select 1 from public.bet_legs where fight_id = 9541) then
    raise exception 'Fight #9541 is attached to a bet ticket. Nothing was deleted.';
  end if;
  -- Block unknown children even when their FK would cascade on deletion.
  for dependency in
    select n.nspname, c.relname, a.attname, cardinality(fk.conkey) as key_count
    from pg_constraint fk
    join pg_class c on c.oid = fk.conrelid
    join pg_namespace n on n.oid = c.relnamespace
    join pg_attribute a on a.attrelid = c.oid and a.attnum = fk.conkey[1]
    where fk.contype = 'f' and fk.confrelid = 'public.fights'::regclass
      and fk.conrelid not in ('public.fight_research'::regclass,
        'public.bet_legs'::regclass, 'public.odds'::regclass,
        'public.mma_odds_observations'::regclass,
        'public.fight_stats'::regclass, 'public.fight_round_stats'::regclass)
  loop
    if dependency.key_count <> 1 then
      raise exception 'An unknown composite dependency references fights. Nothing was deleted.';
    end if;
    execute format('select exists (select 1 from %I.%I where %I = 9541)',
                   dependency.nspname, dependency.relname, dependency.attname)
      into has_dependency;
    if has_dependency then
      raise exception 'Fight #9541 has additional linked data in %.%. Nothing was deleted.',
                       dependency.nspname, dependency.relname;
    end if;
  end loop;
  -- Require the 11 imported official bouts to be present and final. Source
  -- pointers establish provenance even when an older confirmed result is kept.
  select count(*) into completed_count from public.fights f
    where f.event_id = target.event_id and f.fight_id <> 9541
      and (f.fight_status in ('draw', 'no_contest')
           or (f.fight_status = 'completed' and f.winner_id is not null));
  select count(*) into official_count from public.fights f
    where f.event_id = target.event_id and f.fight_id <> 9541
      and exists (select 1 from public.external_ids x
                  join public.data_sources s on s.source_id = x.source_id
                  where x.entity_type = 'fight' and x.internal_id = f.fight_id
                    and s.name = 'PFL Official Event Catalog'
                    and x.external_id like 'pfl-fight:pfl-morocco:%');
  if completed_count <> 11 or official_count <> 11
     or exists (select 1 from public.external_ids x
                join public.data_sources s on s.source_id = x.source_id
                where x.entity_type = 'fight' and x.internal_id = 9541
                  and s.name = 'PFL Official Event Catalog') then
    raise exception 'The 11 imported official results could not be confirmed. Nothing was deleted.';
  end if;
  if exists (select 1 from mma_recovery.fight_cleanups
             where cleanup_key = 'pfl-morocco-9541') then
    raise exception 'A recovery copy already exists and #9541 is present. Nothing was deleted.';
  end if;

  snapshot := jsonb_build_object('event', to_jsonb(event_row),
                                'fights', jsonb_build_array(to_jsonb(target)));
  foreach table_name in array array['odds', 'mma_odds_observations',
                                     'fight_stats', 'fight_round_stats'] loop
    execute format('select coalesce(jsonb_agg(to_jsonb(r)), ''[]''::jsonb)
                    from public.%I r where fight_id = 9541', table_name) into related;
    snapshot := snapshot || jsonb_build_object(table_name, related);
  end loop;
  select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb) into related
    from public.external_ids x where entity_type = 'fight' and internal_id = 9541;
  snapshot := snapshot || jsonb_build_object('external_ids', related);
  select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb) into related
    from public.mma_external_aliases x where entity_type = 'fight' and internal_id = 9541;
  snapshot := snapshot || jsonb_build_object('mma_external_aliases', related);
  insert into mma_recovery.fight_cleanups(cleanup_key, fight_id, payload)
    values ('pfl-morocco-9541', 9541, snapshot);

  delete from public.external_ids where entity_type = 'fight' and internal_id = 9541;
  delete from public.mma_external_aliases where entity_type = 'fight' and internal_id = 9541;
  foreach table_name in array array['odds', 'mma_odds_observations',
                                     'fight_stats', 'fight_round_stats'] loop
    execute format('delete from public.%I where fight_id = 9541', table_name);
  end loop;
  -- Foreign-key constraints and all earlier checks remain inside the transaction.
  delete from public.fights where fight_id = 9541;
end;
$cleanup$;
commit;

select case when exists (select 1 from public.fights where fight_id = 9541)
            then 'Fight #9541 remains; review required.'
            else 'Cleanup complete: fight #9541 removed; recovery copy saved.' end as result;
