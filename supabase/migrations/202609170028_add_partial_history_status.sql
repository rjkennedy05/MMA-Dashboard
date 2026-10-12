-- Distinguish a real debut/no-public-record outcome from a fighter whose
-- public history was found but is incomplete relative to the available record.

alter table public.fighter_history_coverage
  drop constraint if exists fighter_history_coverage_coverage_status_check;

alter table public.fighter_history_coverage
  add constraint fighter_history_coverage_coverage_status_check
  check (coverage_status in (
    'pending',
    'complete',
    'linked_history',
    'fallback_history',
    'partial_history',
    'confirmed_debut',
    'regional_history_unavailable',
    'history_unavailable',
    'needs_review'
  ));

notify pgrst, 'reload schema';
