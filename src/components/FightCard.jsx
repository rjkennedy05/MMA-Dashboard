import { useEffect, useState } from "react";

import { getFightsByEvent } from "../services/fightService";
import { getLatestMoneylinesForFights } from "../services/oddsService";
import { getFightResearchForFights } from "../services/researchService";
import { formatFightStatus, getOfficialResult } from "../utils/fightResults";
import { formatAmericanOdds, getBestMoneyline } from "../utils/odds";
import {
  fighterDecisionClass,
  getResearchDecision,
} from "../utils/researchDecision";

function CompactFighterLine({
  fighter,
  highlightClass = "",
  lines = [],
  koWins = null,
  submissionWins = null,
}) {
  const bestPrice = getBestMoneyline(lines);
  const finishDetails = [
    Number.isInteger(koWins) ? `KO ${koWins}` : null,
    Number.isInteger(submissionWins) ? `SUB ${submissionWins}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <div className="compact-fighter-line">
      <div className="compact-fighter-identity">
        <strong className={highlightClass}>
          {fighter?.full_name ?? "Unknown fighter"}
        </strong>
        <small>
          {fighter?.record_summary ?? "Record —"}
          {finishDetails ? ` · ${finishDetails}` : ""}
        </small>
      </div>
      <span>
        {bestPrice
          ? formatAmericanOdds(bestPrice.american_odds)
          : "—"}
      </span>
    </div>
  );
}

export default function FightCard({
  eventId,
  selectedFightId = null,
  onSelectFight,
  onFightsLoaded,
  onCardChangesLoaded,
  refreshKey = 0,
}) {
  const [fights, setFights] = useState([]);
  const [oddsByFight, setOddsByFight] =
    useState({});
  const [researchByFight, setResearchByFight] =
    useState({});
  const [loading, setLoading] =
    useState(true);
  const [error, setError] =
    useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadFightCard() {
      if (!eventId) {
        setFights([]);
        setOddsByFight({});
        setResearchByFight({});
        onFightsLoaded?.([]);
        onCardChangesLoaded?.([]);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError("");

        const fightData =
          await getFightsByEvent(eventId);

        const activeFights = fightData.filter(
          (fight) => fight.fight_status !== "cancelled"
        );
        const cardChanges = fightData.filter(
          (fight) => fight.fight_status === "cancelled"
        );

        const fightIds = activeFights.map(
          (fight) => fight.fight_id
        );

        const [oddsData, researchData] =
          await Promise.all([
            getLatestMoneylinesForFights(fightIds),
            getFightResearchForFights(fightIds),
          ]);

        if (!cancelled) {
          setFights(activeFights);
          setOddsByFight(oddsData);
          setResearchByFight(researchData);
          onFightsLoaded?.(activeFights);
          onCardChangesLoaded?.(cardChanges);
        }
      } catch (loadError) {
        console.error(
          "Fight card loading error:",
          loadError
        );

        if (!cancelled) {
          setError(
            loadError?.message ??
              "Could not load the fight card."
          );

          setFights([]);
          setOddsByFight({});
          setResearchByFight({});
          onFightsLoaded?.([]);
          onCardChangesLoaded?.([]);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadFightCard();

    return () => {
      cancelled = true;
    };
  }, [eventId, refreshKey, onFightsLoaded, onCardChangesLoaded]);

  if (loading) {
    return (
      <div className="card">
        <h2>Fight Card</h2>
        <p>Loading fights and odds...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <h2>Fight Card</h2>
        <p>{error}</p>
      </div>
    );
  }

  if (fights.length === 0) {
    return (
      <div className="card">
        <h2>Fight Card</h2>
        <p>No fights found for this event.</p>
      </div>
    );
  }

  return (
    <aside className="fight-card-panel">
      <div className="section-heading fight-card-heading">
        <div>
          <h3>Fight card</h3>
          <small>Select a matchup</small>
        </div>

        <span className="event-count">
          {fights.length} fights
        </span>
      </div>

      {fights.map((fight) => {
        const fighterA = fight.fighter_a;
        const fighterB = fight.fighter_b;

        const fightOdds =
          oddsByFight[fight.fight_id] ?? {};

        const fighterAOdds =
          fightOdds[
            fighterA?.fighter_id
          ] ?? [];

        const fighterBOdds =
          fightOdds[
            fighterB?.fighter_id
          ] ?? [];

        const isSelected =
          selectedFightId ===
          fight.fight_id;
        const officialResult = getOfficialResult(fight);
        const researchDecision = getResearchDecision(
          researchByFight[fight.fight_id]
        );
        const fightResearch = researchByFight[fight.fight_id] ?? {};

        return (
          <button
            type="button"
            key={fight.fight_id}
            className={[
              "fight-row",
              "fight-row-button",
              isSelected
                ? "fight-row-selected"
                : "",
            ]
              .filter(Boolean)
              .join(" ")}
            onClick={() => {
              if (
                typeof onSelectFight ===
                "function"
              ) {
                onSelectFight(fight);
              }
            }}
          >
            <div className="fight-row-meta">
              <span>Fight {fight.fight_order ?? "—"}</span>
              <span>
                {fight.weight_classes?.name ?? "Weight unavailable"}
              </span>
              <span
                className={`fight-status fight-status-${fight.fight_status ?? "unknown"}`}
              >
                {formatFightStatus(fight.fight_status)}
              </span>
            </div>

            <div className="compact-matchup">
              <CompactFighterLine
                fighter={fighterA}
                lines={fighterAOdds}
                koWins={fightResearch.fighter_a_ko_wins}
                submissionWins={fightResearch.fighter_a_submission_wins}
                highlightClass={fighterDecisionClass(
                  researchDecision,
                  "fighter_a"
                )}
              />
              <CompactFighterLine
                fighter={fighterB}
                lines={fighterBOdds}
                koWins={fightResearch.fighter_b_ko_wins}
                submissionWins={fightResearch.fighter_b_submission_wins}
                highlightClass={fighterDecisionClass(
                  researchDecision,
                  "fighter_b"
                )}
              />
            </div>
            {officialResult && (
              <div className="official-fight-result">
                <strong>{officialResult.headline}</strong>
                {officialResult.details && (
                  <span>{officialResult.details}</span>
                )}
              </div>
            )}
          </button>
        );
      })}
    </aside>
  );
}
