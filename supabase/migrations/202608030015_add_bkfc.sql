-- Register BKFC's official schedule/card pages and their embedded MMAReg
-- official result feed. No API key is required.
insert into public.data_sources (name)
select 'BKFC Official / MMAReg'
where not exists (
  select 1
  from public.data_sources
  where lower(trim(name)) in (
    'bkfc official / mmareg',
    'bkfc official',
    'bare knuckle fc official'
  )
);

notify pgrst, 'reload schema';
