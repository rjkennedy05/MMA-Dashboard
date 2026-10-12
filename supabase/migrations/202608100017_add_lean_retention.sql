-- Keeps the dashboard focused on current handicapping work instead of building
-- an unbounded fight archive. Any user-created event or fight research protects
-- its parent event permanently, including tracked and graded bets.

create or replace function public.preview_mma_retention(
  keep_days integer default 30
)
returns table (
  event_id bigint,
  event_name text,
  event_date date,
  promotion_name text,
  fight_count bigint
)
language sql
security definer
set search_path = public
as $$
  select
    e.event_id,
    e.event_name,
    e.event_date,
    p.name as promotion_name,
    count(f.fight_id)::bigint as fight_count
  from public.events e
  join public.promotions p on p.promotion_id = e.promotion_id
  left join public.fights f on f.event_id = e.event_id
  where keep_days >= 1
    and e.event_date < current_date - keep_days
    and lower(coalesce(e.event_status, '')) in (
      'completed',
      'cancelled',
      'canceled'
    )
    and not exists (
      select 1
      from public.event_research er
      where er.event_id = e.event_id
    )
    and not exists (
      select 1
      from public.fights protected_fight
      join public.fight_research fr
        on fr.fight_id = protected_fight.fight_id
      where protected_fight.event_id = e.event_id
    )
  group by e.event_id, e.event_name, e.event_date, p.name
  order by e.event_date, e.event_id;
$$;

create or replace function public.apply_mma_retention(
  keep_days integer default 30
)
returns table (
  cutoff_date date,
  events_deleted integer,
  fights_deleted integer
)
language plpgsql
security definer
set search_path = public
as $$
declare
  retained_cutoff date;
  removed_events integer;
  removed_fights integer;
begin
  if keep_days < 1 then
    raise exception 'keep_days must be at least 1';
  end if;

  retained_cutoff := current_date - keep_days;

  create temporary table retention_events on commit drop as
  select preview.event_id
  from public.preview_mma_retention(keep_days) preview;

  select count(*)::integer
    into removed_events
  from retention_events;

  select count(*)::integer
    into removed_fights
  from public.fights f
  join retention_events r on r.event_id = f.event_id;

  delete from public.external_ids x
  using public.fights f, retention_events r
  where x.entity_type = 'fight'
    and x.internal_id = f.fight_id
    and f.event_id = r.event_id;

  delete from public.fight_round_stats stats
  using public.fights f, retention_events r
  where stats.fight_id = f.fight_id
    and f.event_id = r.event_id;

  delete from public.fight_stats stats
  using public.fights f, retention_events r
  where stats.fight_id = f.fight_id
    and f.event_id = r.event_id;

  delete from public.odds o
  using public.fights f, retention_events r
  where o.fight_id = f.fight_id
    and f.event_id = r.event_id;

  delete from public.fights f
  using retention_events r
  where f.event_id = r.event_id;

  delete from public.external_ids x
  using retention_events r
  where x.entity_type = 'event'
    and x.internal_id = r.event_id;

  delete from public.events e
  using retention_events r
  where e.event_id = r.event_id;

  return query select retained_cutoff, removed_events, removed_fights;
end;
$$;

revoke all on function public.preview_mma_retention(integer)
  from public, anon, authenticated;
revoke all on function public.apply_mma_retention(integer)
  from public, anon, authenticated;
grant execute on function public.preview_mma_retention(integer)
  to service_role;
grant execute on function public.apply_mma_retention(integer)
  to service_role;

comment on function public.preview_mma_retention(integer) is
  'Lists unprotected completed/cancelled events older than the lean retention window.';
comment on function public.apply_mma_retention(integer) is
  'Atomically deletes only retention-eligible event data; user research and bets protect the full event.';
