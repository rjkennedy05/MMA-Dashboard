const DEVELOPMENT_EVENT_NAMES = new Set([
  "ufc test event",
  "ufc import test",
]);

export const RECENT_EVENT_DAYS = 30;
export const ALL_CARDS_EVENT_DAYS = 7;

const EVENT_STATUS_LABELS = {
  cancelled: "Cancelled",
  completed: "Completed",
  live: "Live",
  scheduled: "Scheduled",
};

function normalizedEventName(value) {
  return String(value ?? "")
    .trim()
    .toLocaleLowerCase("en-US")
    .replace(/\s+/g, " ");
}

export function isDevelopmentEvent(event) {
  const name = normalizedEventName(event?.event_name);
  return (
    DEVELOPMENT_EVENT_NAMES.has(name) ||
    /^(?:ufc\s+)?(?:import\s+)?test event(?:\s+\d+)?$/.test(name)
  );
}

function normalizedEventStatus(value) {
  const status = String(value ?? "")
    .trim()
    .toLocaleLowerCase("en-US")
    .replace(/[\s-]+/g, "_");

  if (["completed", "complete", "final"].includes(status)) {
    return "completed";
  }

  if (["live", "in_progress", "inprogress"].includes(status)) {
    return "live";
  }

  if (
    ["cancelled", "canceled", "postponed", "abandoned"].includes(
      status
    )
  ) {
    return "cancelled";
  }

  return "scheduled";
}

function shiftIsoDate(dateString, days) {
  const date = new Date(`${dateString}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

export function getEventDisplayStatus(event) {
  return normalizedEventStatus(event?.event_status);
}

export function formatEventStatus(event) {
  return EVENT_STATUS_LABELS[getEventDisplayStatus(event)];
}

export function splitEventWindow(
  events,
  today,
  recentDays = RECENT_EVENT_DAYS,
  futureDays = null
) {
  const recentCutoff = shiftIsoDate(today, -recentDays);
  const futureCutoff =
    futureDays === null ? null : shiftIsoDate(today, futureDays);
  const upcoming = [];
  const recent = [];

  for (const event of events ?? []) {
    if (!event?.event_date) {
      continue;
    }

    const status = getEventDisplayStatus(event);
    const isFuture = event.event_date > today;
    const isTodayAndCurrent =
      event.event_date === today &&
      !["completed", "cancelled"].includes(status);

    if (isFuture || isTodayAndCurrent) {
      if (
        futureCutoff === null ||
        event.event_date <= futureCutoff
      ) {
        upcoming.push(event);
      }
      continue;
    }

    if (event.event_date >= recentCutoff) {
      recent.push(event);
    }
  }

  return { upcoming, recent };
}

export function eventBrowserWindow(events, today, upcomingOnly = false) {
  if (upcomingOnly) {
    const window = splitEventWindow(
      events,
      today,
      0,
      ALL_CARDS_EVENT_DAYS
    );
    return { upcoming: window.upcoming, recent: [] };
  }

  return splitEventWindow(events, today, RECENT_EVENT_DAYS, null);
}

export function eventMatchesSearch(event, query) {
  const normalizedQuery = String(query ?? "")
    .trim()
    .toLocaleLowerCase("en-US");

  if (!normalizedQuery) {
    return true;
  }

  const fighterNames = (event?.fights ?? []).flatMap((fight) => [
    fight?.fighter_a?.full_name,
    fight?.fighter_b?.full_name,
  ]);

  return [
    event?.event_name,
    event?.promotions?.name,
    event?.city,
    event?.state_region,
    event?.country,
    event?.watch_platform,
    ...fighterNames,
  ].some((value) =>
    String(value ?? "")
      .toLocaleLowerCase("en-US")
      .includes(normalizedQuery)
  );
}
