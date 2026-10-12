import { useCallback, useEffect, useMemo, useState } from "react";

import { getEventById } from "../services/eventService";
import DataSyncStatus from "./DataSyncStatus";
import FightCard from "./FightCard";
import FightWorkspace from "./FightWorkspace";
import { Sparkles } from "lucide-react";
import { getPromotionKey } from "../config/promotions";

function formatEventDate(value) {
  if (!value) return "Date unavailable";
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

function formatEventTime(value) {
  if (!value) return "Time TBA";
  return `${new Intl.DateTimeFormat("en-US", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: "America/Chicago",
  }).format(new Date(value))} CT`;
}

export default function FightCenterConsole({
  eventId,
  selectedFight,
  requestedFightId,
  onSelectFight,
  dataRefreshKey,
  resultsRefreshKey,
  workspaceRefreshKey,
  onDataSyncCompleted,
  onResearchSaved,
  onOpenCardResearch,
}) {
  const [event, setEvent] = useState(null);
  const [fights, setFights] = useState([]);
  const [error, setError] = useState("");
  const [cardChanges, setCardChanges] = useState([]);

  useEffect(() => {
    let cancelled = false;
    async function loadEvent() {
      if (!eventId) {
        setEvent(null);
        return;
      }
      try {
        setError("");
        const row = await getEventById(eventId);
        if (!cancelled) setEvent(row);
      } catch (loadError) {
        if (!cancelled) setError(loadError.message ?? "Could not load the selected event.");
      }
    }
    loadEvent();
    return () => { cancelled = true; };
  }, [eventId, dataRefreshKey]);

  useEffect(() => {
    setFights([]);
  }, [eventId]);

  const handleFightsLoaded = useCallback((loadedFights) => {
    setFights(loadedFights);
  }, []);

  useEffect(() => {
    if (!fights.length) return;
    const fightsBelongToSelectedEvent = fights.every(
      (fight) => Number(fight.event_id) === Number(eventId)
    );
    if (!fightsBelongToSelectedEvent) return;
    const targetFightId = requestedFightId ?? selectedFight?.fight_id;
    const matchingFight = fights.find(
      (fight) => Number(fight.fight_id) === Number(targetFightId)
    );
    if (!matchingFight) {
      onSelectFight(fights[0]);
    } else if (matchingFight !== selectedFight) {
      onSelectFight(matchingFight);
    }
  }, [eventId, fights, onSelectFight, requestedFightId, selectedFight]);

  const selectedIndex = useMemo(
    () => fights.findIndex(
      (fight) => Number(fight.fight_id) === Number(selectedFight?.fight_id)
    ),
    [fights, selectedFight?.fight_id]
  );
  const previousFight = selectedIndex > 0 ? fights[selectedIndex - 1] : null;
  const nextFight = selectedIndex >= 0 && selectedIndex < fights.length - 1
    ? fights[selectedIndex + 1]
    : null;
  const location = [event?.city, event?.state_region, event?.country]
    .filter(Boolean)
    .join(", ");

  if (!eventId) {
    return (
      <section className="card fightcenter-console-empty">
        <h2>FightCenter</h2><p>Select a card above to open its matchup workspace.</p>
      </section>
    );
  }

  return (
    <section className="card fightcenter-console">
      <header className="fightcenter-header">
        <div className="fightcenter-event-copy">
          <p className="fightcenter-event-kicker">
            <strong>{event?.promotions?.name ?? "Promotion"}</strong>
            <span>{formatEventDate(event?.event_date)}</span>
            <span>{formatEventTime(event?.event_start_time)}</span>
          </p>
          <h2>{event?.event_name ?? "Loading selected event…"}</h2>
          <p className="fightcenter-event-details">
            <span>{location || "Location TBA"}</span>
            <span>{event?.watch_platform || "Watch TBA"}</span>
          </p>
        </div>
        <div className="fightcenter-header-tools">
          <div className="fightcenter-event-actions">
            {cardChanges.length ? (
              <details className="card-changes-menu">
                <summary>Card changes <span>{cardChanges.length}</span></summary>
                <div>
                  {cardChanges.map((fight) => (
                    <article key={fight.fight_id}>
                      <strong>{fight.fighter_a?.full_name} vs {fight.fighter_b?.full_name}</strong>
                      <small>Removed from the active card · archived research remains saved</small>
                    </article>
                  ))}
                </div>
              </details>
            ) : null}
            <button
              type="button"
              className="card-research-open-button"
              onClick={onOpenCardResearch}
            >
              <Sparkles size={15} /> Card research
            </button>
          </div>
          <DataSyncStatus
            buttonOnly
            promotionKey={getPromotionKey(event?.promotions?.name) ?? "all"}
            onSyncCompleted={onDataSyncCompleted}
          />
        </div>
      </header>
      {error ? <p className="workspace-error">{error}</p> : null}
      <div className="fightcenter-body">
        <FightCard
          eventId={eventId}
          refreshKey={dataRefreshKey + resultsRefreshKey}
          selectedFightId={selectedFight?.fight_id ?? null}
          onSelectFight={onSelectFight}
          onFightsLoaded={handleFightsLoaded}
          onCardChangesLoaded={setCardChanges}
        />
        <FightWorkspace
          fight={selectedFight}
          refreshKey={workspaceRefreshKey + dataRefreshKey}
          onResearchSaved={onResearchSaved}
          onPreviousFight={previousFight ? () => onSelectFight(previousFight) : null}
          onNextFight={nextFight ? () => onSelectFight(nextFight) : null}
        />
      </div>
    </section>
  );
}
