alter table public.events
  add column if not exists event_start_time timestamptz null,
  add column if not exists watch_platform text null;

comment on column public.events.event_start_time is
  'Scheduled start of the first fight. Stored in UTC and displayed in Central Time.';

comment on column public.events.watch_platform is
  'Plain-text viewing platform, such as Paramount+, Prime Video, or YouTube.';

-- Known metadata for the real card already present in the development database.
update public.events
set
  event_start_time = '2026-08-01 14:00:00+00',
  watch_platform = 'Paramount+',
  updated_at = now()
where event_date = '2026-08-01'
  and lower(event_name) like '%medic%rodriguez%';
