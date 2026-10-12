-- Lock the personal dashboard behind Supabase Authentication.
--
-- The Python sync uses the service_role credential and continues to bypass RLS.
-- The browser uses an authenticated user and may read imported data plus edit the
-- two user-authored research tables. Anonymous access is removed from every
-- current table in the public schema.

do $$
declare
  relation record;
begin
  for relation in
    select schemaname, tablename
    from pg_tables
    where schemaname = 'public'
  loop
    execute format(
      'alter table %I.%I enable row level security',
      relation.schemaname,
      relation.tablename
    );

    execute format(
      'revoke all privileges on table %I.%I from anon',
      relation.schemaname,
      relation.tablename
    );

    execute format(
      'grant select on table %I.%I to authenticated',
      relation.schemaname,
      relation.tablename
    );

    execute format(
      'drop policy if exists dashboard_authenticated_read on %I.%I',
      relation.schemaname,
      relation.tablename
    );

    execute format(
      'create policy dashboard_authenticated_read on %I.%I for select to authenticated using (true)',
      relation.schemaname,
      relation.tablename
    );
  end loop;
end
$$;

grant insert, update, delete on public.fight_research to authenticated;
grant insert, update, delete on public.event_research to authenticated;

drop policy if exists dashboard_authenticated_insert on public.fight_research;
drop policy if exists dashboard_authenticated_update on public.fight_research;
drop policy if exists dashboard_authenticated_delete on public.fight_research;

create policy dashboard_authenticated_insert
  on public.fight_research
  for insert
  to authenticated
  with check (true);

create policy dashboard_authenticated_update
  on public.fight_research
  for update
  to authenticated
  using (true)
  with check (true);

create policy dashboard_authenticated_delete
  on public.fight_research
  for delete
  to authenticated
  using (true);

drop policy if exists dashboard_authenticated_insert on public.event_research;
drop policy if exists dashboard_authenticated_update on public.event_research;
drop policy if exists dashboard_authenticated_delete on public.event_research;

create policy dashboard_authenticated_insert
  on public.event_research
  for insert
  to authenticated
  with check (true);

create policy dashboard_authenticated_update
  on public.event_research
  for update
  to authenticated
  using (true)
  with check (true);

create policy dashboard_authenticated_delete
  on public.event_research
  for delete
  to authenticated
  using (true);

notify pgrst, 'reload schema';
