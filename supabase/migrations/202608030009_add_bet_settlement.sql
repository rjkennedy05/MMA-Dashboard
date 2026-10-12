-- Adds settlement fields to the personal bet ticket stored on fight research.
-- Repeat-safe so it can be rerun if Supabase's schema cache needs a refresh.
alter table public.fight_research
  add column if not exists settlement_status text not null default 'pending'
    check (settlement_status in ('pending', 'win', 'loss', 'push', 'void')),
  add column if not exists settled_at timestamptz null;

comment on column public.fight_research.settlement_status is
  'Grading state for the saved personal bet ticket.';

comment on column public.fight_research.settled_at is
  'Time the saved bet ticket was last graded.';

grant select, insert, update on public.fight_research to anon, authenticated;

notify pgrst, 'reload schema';
