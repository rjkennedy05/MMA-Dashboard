-- V6 FightCenter keeps lightweight event and bout history permanently so the
-- dashboard can build fighter dossiers instead of discarding completed cards.
-- Existing research, bets, results, odds, and identifiers are untouched.

alter table public.fighters
  add column if not exists image_url text;

comment on column public.fighters.image_url is
  'Best available official provider headshot URL. The UI falls back to initials.';

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
    null::bigint,
    null::text,
    null::date,
    null::text,
    null::bigint
  where false;
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
begin
  if keep_days < 1 then
    raise exception 'keep_days must be at least 1';
  end if;

  return query select current_date - keep_days, 0, 0;
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
  'V6 compatibility function. Event and fight history is retained permanently.';
comment on function public.apply_mma_retention(integer) is
  'V6 compatibility function. Returns zero deletions because FightCenter requires history.';

notify pgrst, 'reload schema';
