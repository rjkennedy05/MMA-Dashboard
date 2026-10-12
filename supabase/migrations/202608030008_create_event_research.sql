create table if not exists public.event_research (
  event_id bigint primary key references public.events(event_id) on delete cascade,
  owner_id uuid null references auth.users(id) on delete cascade,
  assistant_card_analysis text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists event_research_owner_id_idx
  on public.event_research(owner_id);

comment on table public.event_research is
  'Event-level research, including the single pasted assistant analysis for a full fight card.';

comment on column public.event_research.assistant_card_analysis is
  'One editable full-card assistant response, shared across every fight in the event.';

grant select, insert, update on public.event_research to anon, authenticated;

-- Authentication remains deferred for the local single-user dashboard.
-- Enable owner-scoped RLS before exposing this table in a public deployment.
alter table public.event_research disable row level security;
