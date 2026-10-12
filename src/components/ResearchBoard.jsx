import { ArrowRight, ChevronDown, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getUpcomingResearchBoard } from "../services/researchBoardService";
import { formatAmericanOdds } from "../utils/odds";
import { buildResearchBoardRows, rankLabel } from "../utils/researchRanking";

function formatDate(value) {
  if (!value) return "Date TBA";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T12:00:00Z`));
}

function pickName(row, side) {
  if (side === "fighter_a") return row.fight.fighter_a.full_name;
  if (side === "fighter_b") return row.fight.fighter_b.full_name;
  if (side === "pass") return "Pass";
  return "Not set";
}

export default function ResearchBoard({ refreshKey = 0, onOpenFight }) {
  const [sourceRows, setSourceRows] = useState([]);
  const [oddsByFight, setOddsByFight] = useState({});
  const [filter, setFilter] = useState("ranked");
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [reloadCount, setReloadCount] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        setLoading(true);
        setError("");
        const result = await getUpcomingResearchBoard();
        if (!cancelled) {
          setSourceRows(result.rows);
          setOddsByFight(result.oddsByFight);
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError.message ?? "Could not load researched picks.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [refreshKey, reloadCount]);

  const rows = useMemo(
    () => buildResearchBoardRows(sourceRows, oddsByFight),
    [sourceRows, oddsByFight]
  );
  const visibleRows = rows.filter((row) => {
    if (filter === "ranked") return ["A", "B"].includes(row.assistant_rank);
    if (filter === "target") return row.targetReached;
    if (filter === "movement") return row.significantMove;
    return true;
  });

  return (
    <section className="card research-board-panel">
      <div className="section-heading research-board-heading">
        <div>
          <p className="eyebrow">Upcoming decision queue</p>
          <h2>Research Board</h2>
          <p>Every researched pick, ranked and connected to its current price.</p>
        </div>
        <div className="research-board-heading-actions">
          <span className="research-board-summary">
            <strong>{rows.filter((row) => ["A", "B"].includes(row.assistant_rank)).length}</strong> A/B picks
            <strong>{rows.length}</strong> researched
          </span>
          <button
            type="button"
            className="research-board-toggle"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? "Collapse" : "Open board"}
            <ChevronDown className={expanded ? "expanded" : ""} size={16} />
          </button>
        </div>
      </div>

      {expanded ? <>
      <div className="research-board-filters" aria-label="Research board filters">
        {[
          ["all", "All researched", rows.length],
          ["ranked", "A/B ranked", rows.filter((row) => ["A", "B"].includes(row.assistant_rank)).length],
          ["target", "Target reached", rows.filter((row) => row.targetReached).length],
          ["movement", "Line swings", rows.filter((row) => row.significantMove).length],
        ].map(([value, label, count]) => (
          <button
            type="button"
            key={value}
            className={filter === value ? "active" : ""}
            onClick={() => setFilter(value)}
          >
            {label}<span>{count}</span>
          </button>
        ))}
        <button
          type="button"
          className="research-board-refresh"
          disabled={loading}
          onClick={() => setReloadCount((count) => count + 1)}
        >
          <RefreshCw className={loading ? "spin" : ""} size={13} /> Refresh
        </button>
      </div>

      {error ? <p className="results-error">{error}</p> : null}
      {loading ? <p className="results-empty">Loading researched picks…</p> : null}
      {!loading && visibleRows.length === 0 ? (
        <p className="results-empty">
          {rows.length
            ? "No researched picks match this filter."
            : "Research a matchup or import a fresh card analysis to populate this board."}
        </p>
      ) : null}

      {visibleRows.length ? (
        <div className="research-board-list">
          <div className="research-board-row research-board-row-head">
            <span>Rank</span><span>Matchup</span><span>AI read</span><span>Price</span><span>Signal</span><span />
          </div>
          {visibleRows.map((row) => {
            const movement = row.movement?.probabilityPointChange ?? 0;
            const MovementIcon = movement >= 0 ? TrendingUp : TrendingDown;
            return (
              <button
                type="button"
                className="research-board-row research-board-pick-row"
                key={row.fight.fight_id}
                onClick={() => onOpenFight?.(row)}
              >
                <span className={`research-rank research-rank-${String(row.assistant_rank ?? "none").toLowerCase()}`}>
                  <strong>{row.assistant_rank ? `#${row.overallRank}` : "—"}</strong>
                  <small>Tier {rankLabel(row.assistant_rank)}</small>
                </span>
                <span className="research-board-matchup">
                  <small>{row.event.promotions?.name ?? "Promotion"} · {formatDate(row.event.event_date)}</small>
                  <strong>{row.fight.fighter_a.full_name} vs {row.fight.fighter_b.full_name}</strong>
                  <small>{row.event.event_name}</small>
                </span>
                <span>
                  <strong>{pickName(row, row.assistant_pick)}</strong>
                  <small>
                    {row.assistant_win_probability ? `Win probability ${row.assistant_win_probability}%` : "Probability pending"}
                    {row.assistant_volatility ? ` · Fight volatility: ${row.assistant_volatility}` : ""}
                  </small>
                  <small>Your lean: {pickName(row, row.user_lean)}</small>
                </span>
                <span>
                  <strong>{formatAmericanOdds(row.currentPrice)}</strong>
                  <small>{row.bestLine?.sportsbook ?? "No current book"}</small>
                  <small>Buy at {formatAmericanOdds(row.targetPrice)}</small>
                </span>
                <span className="research-board-signal">
                  {row.targetReached ? <strong className="signal-target">Target reached</strong> : null}
                  {row.significantMove ? (
                    <small className={movement >= 0 ? "signal-shortened" : "signal-drifted"}>
                      <MovementIcon size={13} /> {movement > 0 ? "+" : ""}{movement.toFixed(1)} pp
                    </small>
                  ) : null}
                  {!row.targetReached && !row.significantMove ? <small>No major signal</small> : null}
                </span>
                <ArrowRight size={16} />
              </button>
            );
          })}
        </div>
      ) : null}
      </> : null}
    </section>
  );
}
