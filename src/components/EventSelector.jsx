import { useEffect, useMemo, useState } from "react";

import {
  ALL_CARDS_EVENT_DAYS,
  RECENT_EVENT_DAYS,
  eventBrowserWindow,
  eventMatchesSearch,
  formatEventStatus,
  getEventDisplayStatus,
} from "../utils/events";
import {
  ALL_PROMOTIONS_KEY,
  getPromotionKey,
  getPromotionLabel,
} from "../config/promotions";
import { getUpcomingEvents } from "../services/eventService";
import { getMoneylineCoverageForFights } from "../services/oddsService";
import { getFightResearchCoverageForFights } from "../services/researchService";
import { getDateInTimeZone } from "../utils/date";

const VIEW_OPTIONS = [
  { key: "all", label: "All cards" },
  { key: "upcoming", label: "Upcoming" },
  { key: "recent", label: "Recent" },
];

function formatEventDate(dateString) {
  if (!dateString) {
    return "Date unavailable";
  }

  // Noon prevents date shifts caused by timezone conversion.
  const date = new Date(`${dateString}T12:00:00`);

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function formatCentralTime(dateTimeString) {
  if (!dateTimeString) {
    return "Time TBA";
  }

  return `${new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
  }).format(new Date(dateTimeString))} CT`;
}

function EventOption({ event, coverage, isSelected, onSelectEvent }) {
  const location = [
    event.city,
    event.state_region,
    event.country,
  ]
    .filter(Boolean)
    .join(", ");
  const promotionLabel = getPromotionLabel(
    getPromotionKey(event.promotions?.name)
  );
  const status = getEventDisplayStatus(event);

  return (
    <button
      type="button"
      className={[
        "event-option",
        isSelected ? "event-option-selected" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      aria-pressed={isSelected}
      onClick={() => onSelectEvent(event.event_id)}
    >
      <span className="event-option-schedule">
        <strong>{formatEventDate(event.event_date)}</strong>
        <small>{formatCentralTime(event.event_start_time)}</small>
      </span>

      <span className="event-option-card">
        <span className="event-option-meta">
          <small>{promotionLabel}</small>
          <small className={`event-status-badge event-status-${status}`}>
            {formatEventStatus(event)}
          </small>
        </span>
        <strong>{event.event_name}</strong>
      </span>

      <span className="event-option-location">
        {location || "Location unavailable"}
      </span>

      <span className="event-option-watch">
        <small>Watch</small>
        <strong>{event.watch_platform || "TBA"}</strong>
      </span>

      <span className="event-option-coverage">
        <small>{coverage?.fights ?? event.fights?.length ?? 0} fights</small>
        <small className={coverage?.priced ? "coverage-positive" : ""}>
          {coverage?.priced ?? 0} priced
        </small>
        <small className={coverage?.researched ? "coverage-positive" : ""}>
          {coverage?.researched ?? 0} researched
        </small>
      </span>
    </button>
  );
}

export default function EventSelector({
  selectedPromotionKey,
  selectedEventId,
  onSelectEvent,
  refreshKey = 0,
}) {
  const [events, setEvents] = useState([]);
  const [coverageByEvent, setCoverageByEvent] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [view, setView] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const isAllPromotions = selectedPromotionKey === ALL_PROMOTIONS_KEY;

  useEffect(() => {
    let cancelled = false;

    async function loadEvents() {
      try {
        setLoading(true);
        setError("");

        const eventData = await getUpcomingEvents();
        const fightIds = eventData.flatMap((event) =>
          (event.fights ?? []).map((fight) => fight.fight_id)
        );
        const [pricedFightIds, researchByFight] = await Promise.all([
          getMoneylineCoverageForFights(fightIds).catch(() => new Set()),
          getFightResearchCoverageForFights(fightIds).catch(() => ({})),
        ]);
        const coverage = Object.fromEntries(eventData.map((event) => {
          const eventFightIds = (event.fights ?? []).map((fight) => fight.fight_id);
          const priced = eventFightIds.filter((fightId) =>
            pricedFightIds.has(Number(fightId))
          ).length;
          const researched = eventFightIds.filter((fightId) => {
            const row = researchByFight[fightId];
            return Boolean(
              row?.assistant_pick
              || row?.user_lean
              || (row?.research_status && row.research_status !== "not_started")
            );
          }).length;
          return [event.event_id, {
            fights: eventFightIds.length,
            priced,
            researched,
          }];
        }));

        if (!cancelled) {
          setEvents(eventData);
          setCoverageByEvent(coverage);
        }
      } catch (loadError) {
        console.error("Events loading error:", loadError);

        if (!cancelled) {
          setError(
            loadError.message ?? "Could not load event cards."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadEvents();

    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  useEffect(() => {
    setView("all");
    setSearchQuery("");
  }, [selectedPromotionKey]);

  const supportedEvents = useMemo(
    () =>
      events.filter((event) =>
        Boolean(getPromotionKey(event.promotions?.name))
      ),
    [events]
  );

  const filteredEvents = useMemo(
    () =>
      selectedPromotionKey === ALL_PROMOTIONS_KEY
        ? supportedEvents
        : supportedEvents.filter(
            (event) =>
              getPromotionKey(event.promotions?.name) ===
              selectedPromotionKey
          ),
    [selectedPromotionKey, supportedEvents]
  );

  const searchedEvents = useMemo(
    () =>
      filteredEvents.filter((event) =>
        eventMatchesSearch(event, searchQuery)
      ),
    [filteredEvents, searchQuery]
  );

  const eventWindow = useMemo(
    () => eventBrowserWindow(
      searchedEvents,
      getDateInTimeZone(),
      isAllPromotions
    ),
    [isAllPromotions, searchedEvents]
  );

  const windowLabel = isAllPromotions
    ? `Upcoming across every promotion · next ${ALL_CARDS_EVENT_DAYS} days`
    : `All upcoming · previous ${RECENT_EVENT_DAYS} days`;

  const visibleEvents = useMemo(() => {
    if (isAllPromotions) {
      return eventWindow.upcoming;
    }

    if (view === "upcoming") {
      return eventWindow.upcoming;
    }

    if (view === "recent") {
      return eventWindow.recent;
    }

    return [...eventWindow.upcoming, ...eventWindow.recent];
  }, [eventWindow, isAllPromotions, view]);

  const viewCounts = useMemo(
    () => ({
      all: eventWindow.upcoming.length + eventWindow.recent.length,
      upcoming: eventWindow.upcoming.length,
      recent: eventWindow.recent.length,
    }),
    [eventWindow]
  );

  useEffect(() => {
    if (loading || error) {
      return;
    }

    const selectedStillExists = visibleEvents.some(
      (event) => event.event_id === selectedEventId
    );

    if (!selectedStillExists) {
      onSelectEvent(visibleEvents[0]?.event_id ?? null);
    }
  }, [
    error,
    loading,
    onSelectEvent,
    selectedEventId,
    visibleEvents,
  ]);

  if (loading) {
    return (
      <div className="card">
        <h2>Fight Card Window</h2>
        <p>Loading events...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <h2>Fight Card Window</h2>
        <p>{error}</p>
      </div>
    );
  }

  if (!supportedEvents.length) {
    return (
      <div className="card">
        <h2>Fight Card Window</h2>
        <p>
          No event rows were found for the supported promotions.
        </p>
      </div>
    );
  }

  if (!filteredEvents.length) {
    return (
      <section className="card event-browser">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Event window</p>
            <h2>{getPromotionLabel(selectedPromotionKey)} Events</h2>
          </div>
        </div>

        <p className="empty-state">
          No {getPromotionLabel(selectedPromotionKey)} event rows have
          been imported yet. Promotion recognition is ready, but event
          and fight data still need to be added.
        </p>
      </section>
    );
  }

  return (
    <section className="card event-browser">
      <div className="section-heading">
        <div>
          <p className="eyebrow">
            {windowLabel}
          </p>
          <h2>{isAllPromotions ? "Upcoming cards" : `${getPromotionLabel(selectedPromotionKey)} cards`}</h2>
        </div>

        <span className="event-count">
          {visibleEvents.length}{" "}
          {visibleEvents.length === 1 ? "card" : "cards"}
        </span>
      </div>

      {!isAllPromotions ? <div className="event-browser-controls">
        <input
          type="search"
          className="event-search-input"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search event, fighter, location, or broadcast"
          aria-label="Search fight cards"
        />

          <div className="event-view-filter" aria-label="Event window filter">
            {VIEW_OPTIONS.map((option) => (
              <button
                type="button"
                key={option.key}
                className={
                  view === option.key
                    ? "event-view-button event-view-button-selected"
                    : "event-view-button"
                }
                aria-pressed={view === option.key}
                onClick={() => setView(option.key)}
              >
                {option.label}
                <span>{viewCounts[option.key]}</span>
              </button>
            ))}
          </div>
      </div> : null}

      <div className="event-window-grid">
        {!visibleEvents.length ? (
          <p className="event-window-empty">
            No cards match the current search and filter.
          </p>
        ) : null}

        {(isAllPromotions || view !== "recent") && eventWindow.upcoming.length ? (
          <section className="event-window-section">
            <div className="event-window-heading">
              <h3>Upcoming</h3>
              <span>{eventWindow.upcoming.length}</span>
            </div>

            <div className="event-list">
              {eventWindow.upcoming.map((event) => (
                <EventOption
                  key={event.event_id}
                  event={event}
                  coverage={coverageByEvent[event.event_id]}
                  isSelected={event.event_id === selectedEventId}
                  onSelectEvent={onSelectEvent}
                />
              ))}
            </div>
          </section>
        ) : null}

        {!isAllPromotions && view !== "upcoming" && eventWindow.recent.length ? (
          <section className="event-window-section event-window-recent">
            <div className="event-window-heading">
              <h3>Recent</h3>
              <span>{eventWindow.recent.length}</span>
            </div>

            <div className="event-list">
              {eventWindow.recent.map((event) => (
                <EventOption
                  key={event.event_id}
                  event={event}
                  coverage={coverageByEvent[event.event_id]}
                  isSelected={event.event_id === selectedEventId}
                  onSelectEvent={onSelectEvent}
                />
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </section>
  );
}
