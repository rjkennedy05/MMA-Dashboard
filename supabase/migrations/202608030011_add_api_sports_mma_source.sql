-- Register the PFL schedule/result provider without assigning a hard-coded ID.
insert into public.data_sources (name)
select 'API-Sports MMA'
where not exists (
  select 1
  from public.data_sources
  where lower(name) in ('api-sports mma', 'api-sports', 'api-mma')
);

notify pgrst, 'reload schema';
