-- Structured, no-paid-API capping fields imported from the existing
-- full-card ChatGPT workflow. Existing research and bets are unchanged.

alter table public.fight_research
  add column if not exists assistant_fair_moneyline integer null
    check (
      assistant_fair_moneyline is null
      or assistant_fair_moneyline <= -100
      or assistant_fair_moneyline >= 100
    ),
  add column if not exists assistant_target_price integer null
    check (
      assistant_target_price is null
      or assistant_target_price <= -100
      or assistant_target_price >= 100
    ),
  add column if not exists assistant_rank text null
    check (assistant_rank is null or assistant_rank in ('A', 'B', 'C', 'D')),
  add column if not exists assistant_reliability text null
    check (
      assistant_reliability is null
      or assistant_reliability in ('strong', 'mixed', 'thin')
    ),
  add column if not exists assistant_volatility text null
    check (
      assistant_volatility is null
      or assistant_volatility in ('low', 'medium', 'high')
    ),
  add column if not exists assistant_betting_assessment text not null default '',
  add column if not exists assistant_win_path text not null default '',
  add column if not exists assistant_upset_path text not null default '',
  add column if not exists assistant_confidence_limiter text not null default '',
  add column if not exists assistant_snapshot_at timestamptz null;

comment on column public.fight_research.assistant_target_price is
  'Imported buy-at threshold that preserves an edge; distinct from the assistant fair line and the user target_price.';
comment on column public.fight_research.assistant_rank is
  'Imported A-D matchup rank based on evidence quality, reliability, volatility, and price.';
comment on column public.fight_research.assistant_snapshot_at is
  'Time the structured pre-fight assistant decision was imported for later process grading.';

notify pgrst, 'reload schema';
