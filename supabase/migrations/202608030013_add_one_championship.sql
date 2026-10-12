-- Register ONE's official site as a repeat-safe schedule/result source.
insert into public.data_sources (name)
select 'ONE Championship Official'
where not exists (
  select 1
  from public.data_sources
  where lower(trim(name)) in (
    'one championship official',
    'one championship',
    'one fc'
  )
);

-- ONE cards mix MMA, Muay Thai, kickboxing, and submission grappling.
-- Keep the normalized ruleset and the exact official bout label.
alter table public.fights
  add column if not exists ruleset text null,
  add column if not exists bout_type text null;

comment on column public.fights.ruleset is
  'Normalized combat sport, such as MMA, Muay Thai, Kickboxing, or Submission Grappling.';

comment on column public.fights.bout_type is
  'Provider bout label preserving weight class, ruleset, and championship context.';

notify pgrst, 'reload schema';
