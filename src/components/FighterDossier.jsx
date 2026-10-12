import { useEffect, useMemo, useState } from "react";

import {
  getMatchupHistoryRecords,
  promotionHistorySummary,
} from "../services/fighterHistoryService";
import {
  fighterAge,
  formatHeight,
  formatReach,
} from "../utils/fighterProfile";
import { finishSummary } from "../utils/assistantMatchupFacts";
import {
  historyCoverageLabel,
  historyEmptyMessage,
} from "../utils/historyCoverage";

function initials(name) {
  return String(name ?? "?")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("") || "?";
}

function formatDate(value) {
  if (!value) return "Date unknown";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

function formatTime(seconds) {
  if (!Number.isInteger(seconds) || seconds < 0) return null;
  const minutes = Math.floor(seconds / 60);
  const remaining = String(seconds % 60).padStart(2, "0");
  return `${minutes}:${remaining}`;
}

function methodLabel(entry) {
  if (entry.outcome === "CANCELLED") return "Bout cancelled";
  if (entry.outcome === "SCHEDULED") return "Scheduled";
  const detail = [
    entry.method,
    entry.round ? `R${entry.round}` : null,
    formatTime(entry.timeSeconds),
  ].filter(Boolean);
  return detail.join(" · ") || "Method unavailable";
}

function outcomeClass(outcome) {
  if (outcome === "W") return "history-outcome-win";
  if (outcome === "L") return "history-outcome-loss";
  if (outcome === "CANCELLED") return "history-outcome-cancelled";
  return "history-outcome-neutral";
}

function FighterPhoto({ fighter }) {
  const [failed, setFailed] = useState(false);
  const showImage = fighter.image_url && !failed;
  return (
    <div className="fighter-dossier-photo" aria-label={`${fighter.full_name} profile photo`}>
      {showImage ? (
        <img
          src={fighter.image_url}
          alt={fighter.full_name}
          onError={() => setFailed(true)}
        />
      ) : (
        <span>{initials(fighter.full_name)}</span>
      )}
    </div>
  );
}

function PromotionPath({ history }) {
  const groups = promotionHistorySummary(history);
  if (!groups.length) return <span className="history-coverage-empty">No retained promotion history yet</span>;
  return (
    <div className="promotion-history-list">
      {groups.map((group) => (
        <span key={group.promotion}>
          <strong>{group.promotion}</strong>
          {group.wins}-{group.losses}
          {group.draws ? `-${group.draws}` : ""}
          {group.noContests ? ` · ${group.noContests} NC` : ""}
          {group.cancelled ? ` · ${group.cancelled} cancelled` : ""}
        </span>
      ))}
    </div>
  );
}

function RecentForm({ history }) {
  const resolved = history
    .filter((entry) => ["W", "L", "D", "NC"].includes(entry.outcome))
    .slice(0, 5);
  if (!resolved.length) return <span className="history-coverage-empty">No retained results</span>;
  return (
    <div className="recent-form-strip" aria-label="Last five retained results">
      {resolved.map((entry) => (
        <span className={outcomeClass(entry.outcome)} key={entry.fightId}>
          {entry.outcome}
        </span>
      ))}
    </div>
  );
}

function FighterDossierCard({ fighter, history, finishFacts }) {
  const age = fighterAge(fighter);
  const knownFinishes = finishSummary({
    koWins: finishFacts.koWins,
    submissionWins: finishFacts.submissionWins,
    recordSummary: finishFacts.recordSummary || fighter.record_summary,
  });
  return (
    <article className="fighter-dossier-card">
      <header className="fighter-dossier-identity">
        <FighterPhoto fighter={fighter} />
        <div>
          <strong>{fighter.full_name}</strong>
          {fighter.nickname ? <small>“{fighter.nickname}”</small> : null}
          <span>{finishFacts.recordSummary || fighter.record_summary || "Record unavailable"}</span>
        </div>
      </header>
      <dl className="fighter-dossier-metrics">
        <div><dt>Age</dt><dd>{age ?? "—"}</dd></div>
        <div><dt>Height</dt><dd>{formatHeight(fighter.height_inches)}</dd></div>
        <div><dt>Reach</dt><dd>{formatReach(fighter.reach_inches)}</dd></div>
        <div><dt>Stance</dt><dd>{fighter.stance ?? "—"}</dd></div>
        <div><dt>KO/TKO wins</dt><dd>{finishFacts.koWins ?? "—"}</dd></div>
        <div><dt>SUB wins</dt><dd>{finishFacts.submissionWins ?? "—"}</dd></div>
      </dl>
      <div className="fighter-dossier-finish">
        <span>Finish profile</span><strong>{knownFinishes}</strong>
      </div>
      <div className="fighter-dossier-context">
        <span><small>Country</small><strong>{fighter.nationality ?? "Unknown"}</strong></span>
        <span><small>Last five</small><RecentForm history={history} /></span>
      </div>
      <div className="fighter-dossier-promotions">
        <small>Known promotion history</small>
        <PromotionPath history={history} />
      </div>
    </article>
  );
}

function HistoryTable({ fighter, history, coverage }) {
  const visible = history.slice(0, 12);
  return (
    <section className="fighter-history-column">
      <div className="fighter-history-heading">
        <strong>{fighter.full_name}</strong>
        <span>{history.length} known bout{history.length === 1 ? "" : "s"}</span>
      </div>
      {!visible.length ? (
        <div className="history-coverage-result">
          <strong>{historyCoverageLabel(coverage)}</strong>
          <p className="history-coverage-empty">{historyEmptyMessage(coverage)}</p>
        </div>
      ) : (
        <div className="fighter-history-table">
          {visible.map((entry) => (
            <article className="fighter-history-row" key={entry.fightId}>
              <span className={`history-outcome ${outcomeClass(entry.outcome)}`}>
                {entry.outcome === "CANCELLED" ? "C" : entry.outcome}
              </span>
              <div>
                <strong>
                  {entry.opponent?.full_name ?? "Opponent unavailable"}
                  {entry.opponentRecord ? <small> ({entry.opponentRecord})</small> : null}
                </strong>
                <span>
                  {entry.promotion} · {formatDate(entry.date)}
                  {entry.titleFight ? " · Title fight" : ""}
                </span>
                <span>{methodLabel(entry)}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

export default function FighterDossier({ fight, research }) {
  const [histories, setHistories] = useState({
    fighterA: { history: [], coverage: null },
    fighterB: { history: [], coverage: null },
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadHistory() {
      if (!fight) return;
      try {
        setLoading(true);
        setError("");
        const result = await getMatchupHistoryRecords(fight);
        if (!cancelled) setHistories(result);
      } catch (loadError) {
        console.error("Fighter history loading error:", loadError);
        if (!cancelled) setError(loadError.message ?? "Could not load fighter history.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadHistory();
    return () => { cancelled = true; };
  }, [fight]);

  const facts = useMemo(() => ({
    fighterA: {
      koWins: research.fighter_a_ko_wins,
      submissionWins: research.fighter_a_submission_wins,
      recordSummary: research.fighter_a_record_summary,
    },
    fighterB: {
      koWins: research.fighter_b_ko_wins,
      submissionWins: research.fighter_b_submission_wins,
      recordSummary: research.fighter_b_record_summary,
    },
  }), [research]);

  return (
    <section className="fighter-dossier-panel">
      <div className="matchup-facts-heading">
        <div><p className="eyebrow">Fighter dossier</p><h4>Profiles, finishes &amp; known history</h4></div>
        <small>{loading ? "Loading retained history…" : "Official/provider records plus saved research"}</small>
      </div>
      {error ? <p className="workspace-error fighter-history-error">{error}</p> : null}
      <div className="fighter-dossier-grid">
        <FighterDossierCard fighter={fight.fighter_a} history={histories.fighterA.history} finishFacts={facts.fighterA} />
        <FighterDossierCard fighter={fight.fighter_b} history={histories.fighterB.history} finishFacts={facts.fighterB} />
      </div>
      <details className="fighter-history-details">
        <summary>Fight history, methods, opponents &amp; cancelled bouts</summary>
        <div className="fighter-history-grid">
          <HistoryTable fighter={fight.fighter_a} history={histories.fighterA.history} coverage={histories.fighterA.coverage} />
          <HistoryTable fighter={fight.fighter_b} history={histories.fighterB.history} coverage={histories.fighterB.coverage} />
        </div>
        <p className="history-coverage-note">
          “Known” means retained official/provider rows in this dashboard. Missing history stays clearly labeled instead of being inferred.
        </p>
      </details>
    </section>
  );
}
