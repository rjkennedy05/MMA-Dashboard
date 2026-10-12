import {
  Check,
  ChevronDown,
  ChevronRight,
  Pencil,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  getTrackedBets,
  resetCurrentBetPeriod,
  saveBetSettlement,
} from "../services/resultsService";
import {
  calculateBetProfit,
  groupBetsByPromotionAndEvent,
  getOfficialSettlementSuggestion,
  summarizeBets,
} from "../utils/betResults";
import { getOfficialResult } from "../utils/fightResults";
import { userFacingDataError } from "../utils/dataError";
import BetEditPanel from "./BetEditPanel";

const RESULT_OPTIONS = [
  ["pending", "Pending"],
  ["win", "Win"],
  ["loss", "Loss"],
  ["push", "Push"],
  ["void", "Void"],
];

function formatOdds(value) {
  const odds = Number(value);
  return odds > 0 ? `+${odds}` : `${odds}`;
}

function formatUnits(value, showSign = false) {
  const units = Number(value) || 0;
  const sign = showSign && units > 0 ? "+" : "";
  return `${sign}${units.toFixed(2)}u`;
}

function formatEventDate(value) {
  if (!value) return "Date unavailable";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

function officialResultForBet(bet) {
  if (bet?.ticket_type === "parlay") {
    return null;
  }

  return getOfficialResult({
    ...bet,
    fighter_a_id: bet?.fighter_a?.fighter_id,
    fighter_b_id: bet?.fighter_b?.fighter_id,
  });
}

function SummaryCard({ label, value, detail, tone = "", onClick }) {
  const Element = onClick ? "button" : "div";
  return (
    <Element
      type={onClick ? "button" : undefined}
      className={`roi-summary-card${onClick ? " roi-summary-card-clickable" : ""} ${tone ? `roi-summary-${tone}` : ""}`}
      onClick={onClick}
    >
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </Element>
  );
}

export default function ResultsRoi({ eventId, refreshKey = 0 }) {
  const [bets, setBets] = useState([]);
  const [draftResults, setDraftResults] = useState({});
  const [loading, setLoading] = useState(true);
  const [savingFightId, setSavingFightId] = useState(null);
  const [savedFightId, setSavedFightId] = useState(null);
  const [error, setError] = useState("");
  const [reloadCount, setReloadCount] = useState(0);
  const [activeView, setActiveView] = useState(
    eventId ? { type: "event", id: eventId } : { type: "lifetime" }
  );
  const [expandedPromotions, setExpandedPromotions] = useState({});
  const [editingBetId, setEditingBetId] = useState(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadResults() {
      try {
        setLoading(true);
        setError("");
        const trackedBets = await getTrackedBets();

        if (!cancelled) {
          setBets(trackedBets);
          setDraftResults(
            Object.fromEntries(
              trackedBets.map((bet) => [
                bet.bet_id,
                bet.settlement_status ?? "pending",
              ])
            )
          );
        }
      } catch (loadError) {
        console.error("Results loading error:", loadError);

        if (!cancelled) {
          setError(userFacingDataError(loadError, "Could not load tracked bets."));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadResults();
    return () => {
      cancelled = true;
    };
  }, [refreshKey, reloadCount]);

  const lifetime = useMemo(() => summarizeBets(bets), [bets]);
  const betTree = useMemo(
    () => groupBetsByPromotionAndEvent(bets),
    [bets]
  );

  useEffect(() => {
    setActiveView(eventId ? { type: "event", id: eventId } : { type: "lifetime" });
  }, [eventId]);

  useEffect(() => {
    if (!eventId) return;
    const parent = betTree.find((group) =>
      group.events.some(
        (eventGroup) => String(eventGroup.eventId) === String(eventId)
      )
    );
    if (!parent) return;
    setExpandedPromotions((current) => (
      current[parent.promotion]
        ? current
        : { ...current, [parent.promotion]: true }
    ));
  }, [betTree, eventId]);

  const activeLedger = useMemo(() => {
    if (activeView.type === "pending") {
      const pendingBets = bets.filter(
        (bet) => (bet.settlement_status ?? "pending") === "pending"
      );
      return {
        title: "Open exposure",
        context: "All pending singles and parlays across every promotion",
        bets: pendingBets,
        summary: summarizeBets(pendingBets),
      };
    }

    if (activeView.type === "promotion") {
      const group = betTree.find(
        (entry) => entry.promotion === activeView.promotion
      );
      return {
        title: group ? `${group.promotion} bets` : "Promotion bets",
        context: group ? `${group.events.length} cards` : "",
        bets: group?.bets ?? [],
        summary: group?.summary ?? summarizeBets([]),
      };
    }

    if (activeView.type === "event") {
      const eventBets = bets.filter(
        (bet) => (bet.event_ids ?? [bet.event_id]).some(
          (id) => String(id) === String(activeView.id)
        )
      );
      return {
        title: eventBets[0]?.event_name ?? "Selected event",
        context: eventBets[0]
          ? `${eventBets[0].promotion_name} · ${formatEventDate(eventBets[0].event_date)}`
          : "No tracked bets on this card",
        bets: eventBets,
        summary: summarizeBets(eventBets),
      };
    }

    return {
      title: "Current-period bets",
      context: `${betTree.length} promotions`,
      bets,
      summary: lifetime,
    };
  }, [activeView, betTree, bets, lifetime]);

  function selectPromotion(group) {
    setActiveView({ type: "promotion", promotion: group.promotion });
    setExpandedPromotions((current) => ({
      ...current,
      [group.promotion]: !current[group.promotion],
    }));
  }

  async function persistSettlement(bet, status) {
    const betId = bet.bet_id;
    try {
      setSavingFightId(betId);
      setSavedFightId(null);
      setError("");
      const saved = await saveBetSettlement(bet, status);
      setBets((current) =>
        current.map((item) =>
          item.bet_id === betId ? { ...item, ...saved } : item
        )
      );
      setDraftResults((current) => ({
        ...current,
        [betId]: saved.settlement_status,
      }));
      setSavedFightId(betId);
    } catch (saveError) {
      console.error("Bet settlement saving error:", saveError);
      setError(userFacingDataError(saveError, "Could not save this result."));
    } finally {
      setSavingFightId(null);
    }
  }

  async function handleSave(bet) {
    await persistSettlement(
      bet,
      draftResults[bet.bet_id] ?? "pending"
    );
  }

  function handleBetChanged() {
    setEditingBetId(null);
    setReloadCount((count) => count + 1);
  }

  async function handleResetPeriod() {
    try {
      setResetting(true);
      setError("");
      await resetCurrentBetPeriod();
      setConfirmingReset(false);
      setEditingBetId(null);
      setActiveView({ type: "lifetime" });
      setReloadCount((count) => count + 1);
    } catch (resetError) {
      setError(userFacingDataError(resetError, "Could not reset the current betting period."));
    } finally {
      setResetting(false);
    }
  }

  const netTone = lifetime.netProfit > 0
    ? "positive"
    : lifetime.netProfit < 0
      ? "negative"
      : "";
  const settlementReviews = useMemo(
    () => bets
      .map((bet) => ({
        bet,
        suggestion: getOfficialSettlementSuggestion(bet),
      }))
      .filter(({ suggestion }) => suggestion),
    [bets]
  );

  return (
    <section className="card results-roi-panel">
      <div className="section-heading results-roi-heading">
        <div>
          <p className="eyebrow">Active tickets only</p>
          <h2>Current Record &amp; ROI</h2>
          <p className="results-period-note">
            Prior-period tickets remain archived for background analysis and do not count here.
          </p>
        </div>

        <button
          type="button"
          className="refresh-results-button"
          disabled={loading}
          onClick={() => setReloadCount((count) => count + 1)}
        >
          <RefreshCw className={loading ? "spin" : ""} size={15} />
          Refresh bets
        </button>
      </div>

      {error && <p className="results-error">{error}</p>}

      <div className="roi-summary-grid">
        <SummaryCard
          label="Record"
          value={`${lifetime.wins}-${lifetime.losses}-${lifetime.pushes}`}
          detail={`${lifetime.pending} pending · ${lifetime.voids} void`}
        />
        <SummaryCard
          label="Net units"
          value={formatUnits(lifetime.netProfit, true)}
          detail={`${formatUnits(lifetime.gradedRisk)} graded risk`}
          tone={netTone}
        />
        <SummaryCard
          label="ROI"
          value={`${lifetime.roi > 0 ? "+" : ""}${lifetime.roi.toFixed(1)}%`}
          detail="Net ÷ graded win/loss risk"
          tone={netTone}
        />
        <SummaryCard
          label="Open exposure"
          value={formatUnits(lifetime.pendingRisk)}
          detail={`${lifetime.pending} pending · click to view`}
          onClick={() => setActiveView({ type: "pending" })}
        />
      </div>

      <section className="settlement-review-section">
        <div className="mini-heading settlement-review-heading">
          <div>
            <p className="eyebrow">Official outcomes found</p>
            <h3>Bet Grading Review</h3>
          </div>
          <span className="review-count-badge">
            {settlementReviews.length} ready to review
          </span>
        </div>

        {loading ? (
          <p className="results-empty">Checking official results…</p>
        ) : settlementReviews.length === 0 ? (
          <p className="results-empty review-clear">
            <ShieldCheck size={17} />
            No pending bets have a new official result.
          </p>
        ) : (
          <div className="settlement-review-list">
            {settlementReviews.map(({ bet, suggestion }) => {
              const officialResult = officialResultForBet(bet);
              const projectedProfit = calculateBetProfit({
                ...bet,
                settlement_status: suggestion.status,
              });
              const needsBookReview = suggestion.confidence === "review";

              return (
                <article
                  className={`settlement-review-row ${needsBookReview ? "settlement-review-caution" : ""}`}
                  key={bet.bet_id}
                >
                  <span className="review-bet-summary">
                    <small>{bet.promotion_name} · {formatEventDate(bet.event_date)}</small>
                    <strong>{bet.selection_name ?? "Unknown selection"}</strong>
                    <small>{formatOdds(bet.bet_price)} · {formatUnits(bet.stake_units)} · {bet.bet_sportsbook || "Sportsbook not entered"}</small>
                  </span>

                  <span className="review-official-result">
                    <small>Official result</small>
                    <strong>{officialResult?.headline ?? (bet.ticket_type === "parlay" ? `${bet.legs?.length ?? 0} official legs checked` : "Result recorded")}</strong>
                    <small>{officialResult?.details || suggestion.reason || bet.event_name}</small>
                  </span>

                  <span className="review-suggestion">
                    <small>{needsBookReview ? "Book rule review" : "Suggested grade"}</small>
                    <strong>{suggestion.status}</strong>
                    <small>{suggestion.reason}</small>
                  </span>

                  <strong
                    className={
                      projectedProfit > 0
                        ? "profit-positive"
                        : projectedProfit < 0
                          ? "profit-negative"
                          : ""
                    }
                  >
                    {formatUnits(projectedProfit, true)}
                  </strong>

                  <button
                    type="button"
                    className={needsBookReview ? "review-result-button review-result-caution" : "review-result-button"}
                    disabled={savingFightId === bet.bet_id}
                    onClick={() => persistSettlement(bet, suggestion.status)}
                  >
                    {needsBookReview ? <TriangleAlert size={15} /> : <ShieldCheck size={15} />}
                    {savingFightId === bet.bet_id
                      ? "Saving…"
                      : needsBookReview
                        ? "Confirm void"
                        : `Accept ${suggestion.status}`}
                  </button>
                </article>
              );
            })}
          </div>
        )}
      </section>

      <div className="results-layout results-browser-layout">
        <aside className="bet-tree-section">
          <div className="mini-heading">
            <div>
              <p className="eyebrow">Browse results</p>
              <h3>Bet History</h3>
            </div>
            {!confirmingReset ? (
              <button
                type="button"
                className="reset-period-button"
                disabled={loading || bets.length === 0}
                onClick={() => setConfirmingReset(true)}
              >
                <RotateCcw size={14} /> Reset period
              </button>
            ) : null}
          </div>

          {confirmingReset ? (
            <div className="reset-period-confirmation">
              <strong>Restart the visible record at 0–0?</strong>
              <small>
                All {bets.length} current tickets will be archived for background analysis, not deleted.
              </small>
              <div>
                <button
                  type="button"
                  disabled={resetting}
                  onClick={() => setConfirmingReset(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="confirm-reset-button"
                  disabled={resetting}
                  onClick={handleResetPeriod}
                >
                  {resetting ? "Resetting…" : "Confirm reset"}
                </button>
              </div>
            </div>
          ) : null}

          {loading ? <p className="results-empty">Loading saved bets…</p> : null}
          {!loading && betTree.length === 0 ? (
            <p className="results-empty">
              Promotion and card branches appear after your first saved bet.
            </p>
          ) : (
            <nav className="bet-tree" aria-label="Bet history by promotion and card">
              <button
                type="button"
                className={activeView.type === "lifetime" ? "bet-tree-root active" : "bet-tree-root"}
                onClick={() => setActiveView({ type: "lifetime" })}
              >
                <span>
                  <strong>Current period</strong>
                  <small>{lifetime.tracked} bets · {lifetime.wins}-{lifetime.losses}-{lifetime.pushes}</small>
                </span>
                <strong className={lifetime.netProfit > 0 ? "profit-positive" : lifetime.netProfit < 0 ? "profit-negative" : ""}>
                  {formatUnits(lifetime.netProfit, true)}
                </strong>
              </button>

              <button
                type="button"
                className={activeView.type === "pending" ? "bet-tree-root active" : "bet-tree-root"}
                onClick={() => setActiveView({ type: "pending" })}
              >
                <span>
                  <strong>Open exposure</strong>
                  <small>{lifetime.pending} pending tickets across all promotions</small>
                </span>
                <strong>{formatUnits(lifetime.pendingRisk)}</strong>
              </button>

              {betTree.map((group) => {
                const expanded = Boolean(expandedPromotions[group.promotion]);
                const selected = activeView.type === "promotion"
                  && activeView.promotion === group.promotion;

                return (
                  <div className="bet-tree-promotion" key={group.promotion}>
                    <button
                      type="button"
                      className={selected ? "bet-tree-promotion-row active" : "bet-tree-promotion-row"}
                      aria-expanded={expanded}
                      onClick={() => selectPromotion(group)}
                    >
                      {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                      <span>
                        <strong>{group.promotion}</strong>
                        <small>{group.summary.tracked} bets · {group.events.length} cards</small>
                      </span>
                      <span>
                        <strong className={group.summary.netProfit > 0 ? "profit-positive" : group.summary.netProfit < 0 ? "profit-negative" : ""}>
                          {formatUnits(group.summary.netProfit, true)}
                        </strong>
                        <small>{group.summary.roi.toFixed(1)}% ROI</small>
                      </span>
                    </button>

                    {expanded ? (
                      <div className="bet-tree-events">
                        {group.events.map((eventGroup) => {
                          const eventSelected = activeView.type === "event"
                            && String(activeView.id) === String(eventGroup.eventId);
                          return (
                            <button
                              type="button"
                              className={eventSelected ? "bet-tree-event active" : "bet-tree-event"}
                              key={eventGroup.eventId ?? eventGroup.eventName}
                              onClick={() => setActiveView({ type: "event", id: eventGroup.eventId })}
                            >
                              <span>
                                <strong>{eventGroup.eventName}</strong>
                                <small>{formatEventDate(eventGroup.eventDate)} · {eventGroup.summary.tracked} bets</small>
                              </span>
                              <strong className={eventGroup.summary.netProfit > 0 ? "profit-positive" : eventGroup.summary.netProfit < 0 ? "profit-negative" : ""}>
                                {formatUnits(eventGroup.summary.netProfit, true)}
                              </strong>
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </nav>
          )}
        </aside>

        <section className="card-results-section bet-ledger-section">
          <div className="mini-heading bet-ledger-heading">
            <div>
              <p className="eyebrow">Selected branch</p>
              <h3>{activeLedger.title}</h3>
              <small>{activeLedger.context}</small>
            </div>
            <span className="rating-key">
              {activeLedger.summary.wins}-{activeLedger.summary.losses}-{activeLedger.summary.pushes}
              {` · ${formatUnits(activeLedger.summary.netProfit, true)}`}
            </span>
          </div>

          {loading ? (
            <p className="results-empty">Loading saved bets…</p>
          ) : activeLedger.bets.length === 0 ? (
            <p className="results-empty">No complete bet tickets are saved in this branch.</p>
          ) : (
            <div className="results-table">
              <div className="results-table-head">
                <span>Selection</span>
                <span>Ticket</span>
                <span>Result</span>
                <span>P/L</span>
                <span />
              </div>

              {activeLedger.bets.map((bet) => {
                const draftStatus = draftResults[bet.bet_id] ?? "pending";
                const officialSuggestion = getOfficialSettlementSuggestion(bet);
                const projectedProfit = calculateBetProfit({
                  ...bet,
                  settlement_status: draftStatus,
                });
                const hasChange = draftStatus !== (bet.settlement_status ?? "pending");
                const editing = editingBetId === bet.bet_id;

                return (
                  <div className="result-ticket-block" key={bet.bet_id}>
                    <div className="results-table-row">
                      <span className="result-selection">
                        <strong>{bet.selection_name ?? "Unknown selection"}</strong>
                        <small>{bet.event_name}</small>
                        {bet.ticket_type === "parlay" ? (
                          <span className="parlay-leg-summary">
                            {(bet.legs ?? []).map((leg) => (
                              <small key={leg.leg_id}>
                                {leg.selection_name} {formatOdds(leg.leg_price)}
                              </small>
                            ))}
                          </span>
                        ) : null}
                        {officialSuggestion && (
                          <button
                            type="button"
                            className="official-result-suggestion"
                            onClick={() => {
                              setSavedFightId(null);
                              setDraftResults((current) => ({
                                ...current,
                                [bet.bet_id]: officialSuggestion.status,
                              }));
                            }}
                            title={officialSuggestion.reason}
                          >
                            {officialSuggestion.confidence === "review"
                              ? `Review suggested ${officialSuggestion.status}`
                              : `Use suggested ${officialSuggestion.status}`}
                          </button>
                        )}
                      </span>
                      <span className="result-ticket">
                        <strong>{formatOdds(bet.bet_price)} · {formatUnits(bet.stake_units)}</strong>
                        <small>{bet.bet_sportsbook || "Sportsbook not entered"}</small>
                      </span>
                      <select
                        aria-label={`${bet.selection_name} result`}
                        value={draftStatus}
                        onChange={(event) => {
                          setSavedFightId(null);
                          setDraftResults((current) => ({
                            ...current,
                            [bet.bet_id]: event.target.value,
                          }));
                        }}
                      >
                        {RESULT_OPTIONS.map(([value, label]) => (
                          <option value={value} key={value}>{label}</option>
                        ))}
                      </select>
                      <strong
                        className={
                          projectedProfit > 0
                            ? "profit-positive"
                            : projectedProfit < 0
                              ? "profit-negative"
                              : ""
                        }
                      >
                        {formatUnits(projectedProfit, true)}
                      </strong>
                      <div className="result-row-actions">
                        <button
                          type="button"
                          className="save-result-button"
                          disabled={savingFightId === bet.bet_id || !hasChange}
                          onClick={() => handleSave(bet)}
                        >
                          {savedFightId === bet.bet_id && !hasChange
                            ? <Check size={15} />
                            : <Save size={15} />}
                          {savingFightId === bet.bet_id
                            ? "Saving…"
                            : savedFightId === bet.bet_id && !hasChange
                              ? "Saved"
                              : "Save"}
                        </button>
                        <button
                          type="button"
                          className={editing ? "edit-bet-button active" : "edit-bet-button"}
                          onClick={() => setEditingBetId(editing ? null : bet.bet_id)}
                        >
                          <Pencil size={14} /> Edit
                        </button>
                      </div>
                    </div>
                    {editing ? (
                      <BetEditPanel
                        bet={bet}
                        onClose={() => setEditingBetId(null)}
                        onChanged={handleBetChanged}
                      />
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
