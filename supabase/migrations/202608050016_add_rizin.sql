-- Register RIZIN's official event, card, fighter, and result pages.
-- No API key is required. Existing research remains attached to reused rows.
insert into public.data_sources (name)
select 'RIZIN Official'
where not exists (
  select 1
  from public.data_sources
  where lower(trim(name)) in (
    'rizin official',
    'rizin ff official',
    'rizin'
  )
);

insert into public.promotions (name, sport)
select 'RIZIN', 'MMA'
where not exists (
  select 1
  from public.promotions
  where lower(trim(name)) in (
    'rizin',
    'rizin fighting federation',
    'rizin ff'
  )
);

notify pgrst, 'reload schema';
