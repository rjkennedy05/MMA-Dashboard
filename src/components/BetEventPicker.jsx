import { CalendarDays } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getPromotionKey, getPromotionLabel } from "../config/promotions";
import { getUpcomingEvents } from "../services/eventService";
import { getDateInTimeZone } from "../utils/date";

function formatDate(value) {
  if (!value) return "Date TBA";
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

export default function BetEventPicker({ selectedEventId, onSelectEvent, refreshKey = 0 }) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        setError("");
        const rows = await getUpcomingEvents();
        if (!cancelled) setEvents(rows);
      } catch (loadError) {
        if (!cancelled) setError(loadError.message ?? "Could not load upcoming cards.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [refreshKey]);

  const upcoming = useMemo(() => {
    const today = getDateInTimeZone();
    return events
      .filter((event) => (
        event.event_date >= today
        && Boolean(getPromotionKey(event.promotions?.name))
      ))
      .slice(0, 12);
  }, [events]);

  useEffect(() => {
    if (loading || error || !upcoming.length) return;
    const selectedIsUpcoming = upcoming.some(
      (event) => String(event.event_id) === String(selectedEventId)
    );
    if (!selectedIsUpcoming) onSelectEvent(upcoming[0].event_id);
  }, [error, loading, onSelectEvent, selectedEventId, upcoming]);

  return (
    <section className="card bet-event-picker">
      <div className="bet-event-picker-heading">
        <span><CalendarDays size={16} /></span>
        <div>
          <strong>Betting card</strong>
          <small>Choose an event, then click one fighter for a single or several for a parlay.</small>
        </div>
      </div>

      {loading ? <p>Loading upcoming cards…</p> : null}
      {error ? <p className="results-error">{error}</p> : null}
      {!loading && !error ? (
        <div className="bet-event-chip-list">
          {upcoming.map((event) => (
            <button
              type="button"
              key={event.event_id}
              className={String(event.event_id) === String(selectedEventId) ? "active" : ""}
              onClick={() => onSelectEvent(event.event_id)}
            >
              <small>{getPromotionLabel(getPromotionKey(event.promotions?.name))} · {formatDate(event.event_date)}</small>
              <strong>{event.event_name}</strong>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}
