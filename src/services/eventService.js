import { readRows } from "./readRows";
import { supabase } from "../lib/supabase";
import { getDateInTimeZone } from "../utils/date";
import { isDevelopmentEvent, RECENT_EVENT_DAYS } from "../utils/events";
import { dedupeEventFights } from "../utils/fights";

function shiftDate(value, days) {
  const date = new Date(`${value}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function compareFightCounts(a, b) {
  return (b.fights?.length ?? 0) - (a.fights?.length ?? 0);
}

export function selectDashboardEvents(
  events,
  today = getDateInTimeZone()
) {
  const datedEvents = (events ?? []).filter(
    (event) => event.event_date && !isDevelopmentEvent(event)
  );

  const upcomingEvents = datedEvents
    .filter((event) => event.event_date >= today)
    .sort(
      (a, b) =>
        a.event_date.localeCompare(b.event_date) ||
        compareFightCounts(a, b)
    );

  const recentEvents = datedEvents
    .filter((event) => event.event_date < today)
    .sort(
      (a, b) =>
        b.event_date.localeCompare(a.event_date) ||
        compareFightCounts(a, b)
    );

  return [...upcomingEvents, ...recentEvents];
}

export async function getUpcomingEvents() {
  const today = getDateInTimeZone();
  const previewStart = shiftDate(today, -RECENT_EVENT_DAYS);
  const data=await readRows(()=>supabase
    .from("events")
    .select(`
      *,
      promotions (
        name
      ),
      fights (
        fight_id,
        fighter_a_id,
        fighter_b_id,
        fight_order,
        fight_status,
        event_id,
        ruleset,
        bout_type,
        fighter_a:fighters!fights_fighter_a_id_fkey (
          full_name
        ),
        fighter_b:fighters!fights_fighter_b_id_fkey (
          full_name
        )
      )
    `)
    .gte("event_date", previewStart)
    .order("event_date", {
      ascending: false,
    }),"event_id");
  const error=null;

  if (error) {
    throw error;
  }

  return selectDashboardEvents((data ?? []).map((event) => ({
    ...event,
    fights: dedupeEventFights(event.fights ?? []),
  })));
}

export async function getEventById(eventId) {
  if (!eventId) return null;
  const { data, error } = await supabase
    .from("events")
    .select(`
      *,
      promotions (name)
    `)
    .eq("event_id", eventId)
    .maybeSingle();
  if (error) throw error;
  return data;
}
