create extension if not exists pgcrypto;

create table if not exists public.fight_research (
  research_id uuid primary key default gen_random_uuid(),
  fight_id bigint not null unique references public.fights(fight_id) on delete cascade,
  owner_id uuid null references auth.users(id) on delete cascade,
  research_status text not null default 'not_started'
    check (research_status in (
      'not_started',
      'initial_lean',
      'researching',
      'waiting_for_price',
      'bet_placed',
      'pass'
    )),
  fighter_a_ratings jsonb not null default '{}'::jsonb,
  fighter_b_ratings jsonb not null default '{}'::jsonb,
  matchup_notes text not null default '',
  competition_notes text not null default '',
  trend_notes text not null default '',
  fighter_a_path text not null default '',
  fighter_b_path text not null default '',
  user_lean text null
    check (user_lean is null or user_lean in ('fighter_a', 'fighter_b', 'wait', 'pass')),
  target_price integer null,
  confidence smallint null
    check (confidence between 1 and 5),
  final_action text not null default 'researching'
    check (final_action in ('researching', 'wait', 'bet', 'pass')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists fight_research_owner_id_idx
  on public.fight_research(owner_id);

comment on table public.fight_research is
  'Personal matchup research created in the handicapping dashboard.';

comment on column public.fight_research.owner_id is
  'Reserved for the authentication milestone. The local single-user MVP leaves this null.';

grant select, insert, update on public.fight_research to anon, authenticated;

-- RLS is intentionally deferred until dashboard authentication is added.
-- Do not expose this table from a public deployment before enabling owner policies.
