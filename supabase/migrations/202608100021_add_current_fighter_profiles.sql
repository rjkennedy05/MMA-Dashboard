-- Stores only the latest provider-supplied fighter snapshot. This is not a
-- career-history table and each sync replaces the prior snapshot in place.
alter table public.fighters
  add column if not exists record_summary text,
  add column if not exists age_snapshot smallint,
  add column if not exists profile_source_id bigint references public.data_sources(source_id),
  add column if not exists profile_updated_at timestamptz;

alter table public.fighters
  drop constraint if exists fighters_age_snapshot_check;

alter table public.fighters
  add constraint fighters_age_snapshot_check
  check (age_snapshot is null or age_snapshot between 14 and 80);
