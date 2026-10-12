-- Repeat-safe repair for projects where the source-pick or assistant-analysis
-- migration was skipped, partially copied, or not yet visible to PostgREST.
alter table public.fight_research
  add column if not exists source_picks jsonb not null default '[]'::jsonb,
  add column if not exists assistant_matchup_summary text not null default '',
  add column if not exists assistant_fighter_a_path text not null default '',
  add column if not exists assistant_fighter_b_path text not null default '',
  add column if not exists assistant_counterargument text not null default '',
  add column if not exists assistant_pick text null
    check (
      assistant_pick is null
      or assistant_pick in ('fighter_a', 'fighter_b', 'pass')
    ),
  add column if not exists assistant_win_probability smallint null
    check (
      assistant_win_probability is null
      or assistant_win_probability between 1 and 99
    );

comment on column public.fight_research.source_picks is
  'Up to five labeled outside sources and their fighter or pass selections.';

comment on column public.fight_research.assistant_matchup_summary is
  'Independent assistant matchup analysis, kept separate from user-authored notes.';

comment on column public.fight_research.assistant_pick is
  'Assistant estimated winner or pass.';

comment on column public.fight_research.assistant_win_probability is
  'Whole-number win probability for the assistant-selected fighter; fair moneyline is derived in the dashboard.';

grant select, insert, update on public.fight_research to anon, authenticated;

-- Supabase/PostgREST may otherwise keep serving an older schema cache briefly.
notify pgrst, 'reload schema';
