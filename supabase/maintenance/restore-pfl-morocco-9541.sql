-- Optional recovery of the one-time cleanup. Run only to undo that cleanup.
-- Restores original IDs and source rows; conflicts roll back the whole restore.
begin;
set local lock_timeout = '5s';
set local statement_timeout = '30s';
do $restore$
declare
  backup mma_recovery.fight_cleanups;
  table_name text;
  related jsonb;
begin
  perform public.mma_check_import_lease(null, null);
  select * into strict backup from mma_recovery.fight_cleanups
    where cleanup_key = 'pfl-morocco-9541' for update;
  if backup.restored_at is not null then
    return;
  end if;
  if exists (select 1 from public.fights where fight_id = 9541) then
    raise exception 'Fight #9541 already exists. Recovery did not overwrite it.';
  end if;
  foreach table_name in array array['fights', 'odds', 'mma_odds_observations',
      'fight_stats', 'fight_round_stats', 'external_ids', 'mma_external_aliases'] loop
    related := backup.payload -> table_name;
    execute format('insert into public.%I overriding system value
                    select * from jsonb_populate_recordset(null::public.%I, $1)',
                    table_name, table_name) using related;
  end loop;
  update mma_recovery.fight_cleanups set restored_at = now()
    where cleanup_key = 'pfl-morocco-9541';
end;
$restore$;
commit;
select 'Recovery complete: the original #9541 data was restored.' as result;
