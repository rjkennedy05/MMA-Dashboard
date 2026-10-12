-- Starts the focused FightCenter tracking period without deleting prior bets.
-- Existing singles and parlays are archived exactly once and remain available
-- to background capping diagnostics. New tickets begin the visible record at 0.

begin;

do $$
declare
  first_single_archive boolean;
begin
  select not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'fight_research'
      and column_name = 'bet_archived_at'
  ) into first_single_archive;

  alter table public.fight_research
    add column if not exists bet_archived_at timestamptz null;

  if first_single_archive then
    update public.fight_research
    set bet_archived_at = now()
    where bet_side is not null
      and bet_price is not null
      and coalesce(stake_units, 0) > 0;
  end if;
end $$;

do $$
declare
  first_parlay_archive boolean;
begin
  select not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'bet_tickets'
      and column_name = 'archived_at'
  ) into first_parlay_archive;

  alter table public.bet_tickets
    add column if not exists archived_at timestamptz null;

  if first_parlay_archive then
    update public.bet_tickets
    set archived_at = now()
    where archived_at is null;
  end if;
end $$;

alter table public.fight_research
  add column if not exists assistant_matchup_analysis text not null default '';

create index if not exists fight_research_active_bet_idx
  on public.fight_research(fight_id)
  where bet_archived_at is null
    and bet_side is not null;

create index if not exists bet_tickets_active_owner_idx
  on public.bet_tickets(owner_id, placed_at desc)
  where archived_at is null;

comment on column public.fight_research.bet_archived_at is
  'When set, the historical single is excluded from the current visible tracking period but remains available to background diagnostics.';
comment on column public.bet_tickets.archived_at is
  'When set, the historical parlay is excluded from the current visible tracking period but remains available to background diagnostics.';
comment on column public.fight_research.assistant_matchup_analysis is
  'Persisted matchup-specific narrative extracted from the saved full-card assistant response.';

notify pgrst, 'reload schema';

commit;
