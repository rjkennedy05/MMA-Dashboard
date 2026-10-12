-- Register the combined LFA schedule/card provider. The official LFA calendar
-- supplies announced events while Sherdog supplies card and result detail.
insert into public.data_sources (name)
select 'LFA Official / Sherdog'
where not exists (
  select 1
  from public.data_sources
  where lower(trim(name)) in (
    'lfa official / sherdog',
    'lfa composite',
    'sherdog lfa'
  )
);

notify pgrst, 'reload schema';
