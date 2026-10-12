alter table public.fight_research
  add column if not exists source_picks jsonb not null default '[]'::jsonb;

comment on column public.fight_research.source_picks is
  'Up to five labeled outside sources and their fighter or pass selections.';
