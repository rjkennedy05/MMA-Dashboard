-- Provider feeds can report an event as live while it is in progress. The
-- original project constraint predates live-card browsing and rejects that
-- otherwise valid transition.

alter table public.events
  drop constraint if exists events_event_status_check;

alter table public.events
  add constraint events_event_status_check
  check (
    event_status is null
    or lower(event_status) in (
      'upcoming',
      'scheduled',
      'live',
      'in_progress',
      'completed',
      'final',
      'cancelled',
      'canceled',
      'postponed',
      'unknown'
    )
  );

comment on constraint events_event_status_check on public.events is
  'Allows provider schedule, live, final, cancellation, and legacy status values.';
