-- Adds the personal bet ticket to the existing fight research record.
-- Repeat-safe so it can be rerun if Supabase's schema cache lags behind.
alter table public.fight_research
  add column if not exists bet_side text null
    check (bet_side is null or bet_side in ('fighter_a', 'fighter_b')),
  add column if not exists bet_sportsbook text not null default '',
  add column if not exists bet_price integer null
    check (bet_price is null or bet_price <= -100 or bet_price >= 100),
  add column if not exists stake_units numeric(7, 2) null
    check (stake_units is null or stake_units >= 0);

comment on column public.fight_research.bet_side is
  'Fighter selected on the saved personal bet ticket.';

comment on column public.fight_research.bet_sportsbook is
  'Sportsbook where the wager was placed.';

comment on column public.fight_research.bet_price is
  'American moneyline accepted when the wager was placed.';

comment on column public.fight_research.stake_units is
  'Stake expressed in bankroll units.';

grant select, insert, update on public.fight_research to anon, authenticated;

notify pgrst, 'reload schema';
