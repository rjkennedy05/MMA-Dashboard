import { Check, RotateCcw, Save, Sparkles, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { BET_SPORTSBOOKS, sportsbookMatches } from "../config/sportsbooks";
import { getFightsByEvent } from "../services/fightService";
import { getLatestMoneylinesForFights } from "../services/oddsService";
import { getFightResearchForFights } from "../services/researchService";
import {
  getTrackedBets,
  saveParlayTicket,
  saveSingleBet,
} from "../services/resultsService";
import {
  americanOddsToDecimal,
  combineAmericanOdds,
  formatAmericanOdds,
} from "../utils/odds";

function emptyTicket() {
  return { ticketLabel: "", sportsbook: "", ticketPrice: "", stakeUnits: "" };
}

function currentPrice(oddsByFight, fight, side, sportsbook) {
  const fighterId = side === "fighter_a"
    ? fight?.fighter_a?.fighter_id
    : side === "fighter_b"
      ? fight?.fighter_b?.fighter_id
      : null;
  const lines = oddsByFight?.[fight?.fight_id]?.[fighterId] ?? [];
  return lines.find((line) => sportsbookMatches(line, sportsbook))?.american_odds ?? "";
}

function sideLabel(fight, side) {
  return side === "fighter_a" ? fight.fighter_a.full_name : fight.fighter_b.full_name;
}

export default function ParlayEntry({ eventId, onSaved }) {
  const [fights, setFights] = useState([]);
  const [oddsByFight, setOddsByFight] = useState({});
  const [researchByFight, setResearchByFight] = useState({});
  const [pendingFightIds, setPendingFightIds] = useState(new Set());
  const [ticket, setTicket] = useState(emptyTicket);
  const [manualCombinedPrice, setManualCombinedPrice] = useState(false);
  const [legDrafts, setLegDrafts] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadCandidates() {
      setTicket(emptyTicket());
      setManualCombinedPrice(false);
      setLegDrafts({});
      setSaved(false);
      setError("");
      if (!eventId) {
        setFights([]);
        setOddsByFight({});
        setResearchByFight({});
        return;
      }

      try {
        setLoading(true);
        const eventFights = await getFightsByEvent(eventId);
        const fightIds = eventFights.map((fight) => fight.fight_id);
        const [odds, research, trackedBets] = await Promise.all([
          getLatestMoneylinesForFights(fightIds),
          getFightResearchForFights(fightIds),
          getTrackedBets(),
        ]);
        const exposed = new Set(trackedBets
          .filter((bet) => (bet.settlement_status ?? "pending") === "pending")
          .flatMap((bet) => bet.ticket_type === "parlay"
            ? (bet.legs ?? []).map((leg) => leg.fight_id)
            : [bet.fight_id])
          .map(Number));
        if (!cancelled) {
          setFights(eventFights);
          setOddsByFight(odds);
          setResearchByFight(research);
          setPendingFightIds(exposed);
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError.message ?? "Could not load betting candidates.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    loadCandidates();
    return () => { cancelled = true; };
  }, [eventId]);

  const selectedLegs = useMemo(() => fights.flatMap((fight) => {
    const draft = legDrafts[fight.fight_id];
    return draft?.bet_side ? [{ fight, ...draft }] : [];
  }), [fights, legDrafts]);
  const ticketMode = selectedLegs.length === 1
    ? "single"
    : selectedLegs.length > 1
      ? "parlay"
      : "empty";
  const calculatedPrice = selectedLegs.length === 1
    ? selectedLegs[0].leg_price
    : combineAmericanOdds(selectedLegs.map((leg) => leg.leg_price));
  const displayedTicketPrice = manualCombinedPrice ? ticket.ticketPrice : calculatedPrice ?? "";
  const decimalPrice = americanOddsToDecimal(displayedTicketPrice);
  const stake = Number(ticket.stakeUnits);
  const potentialProfit = decimalPrice && stake > 0 ? stake * (decimalPrice - 1) : null;

  const suggested = useMemo(() => fights.map((fight) => {
    const research = researchByFight[fight.fight_id] ?? {};
    return { fight, research };
  }).filter(({ research }) =>
    ["fighter_a", "fighter_b"].includes(research.assistant_pick)
    && ["A", "B", "C"].includes(research.assistant_rank)
    && research.assistant_volatility !== "high"
  ).sort((left, right) =>
    ({ A: 0, B: 1, C: 2 }[left.research.assistant_rank] ?? 9)
    - ({ A: 0, B: 1, C: 2 }[right.research.assistant_rank] ?? 9)
    || (right.research.assistant_win_probability ?? 0)
    - (left.research.assistant_win_probability ?? 0)
  ), [fights, researchByFight]);

  function updateSportsbook(sportsbook) {
    setSaved(false);
    setTicket((current) => ({ ...current, sportsbook }));
    setManualCombinedPrice(false);
    setLegDrafts((current) => Object.fromEntries(fights.map((fight) => {
      const draft = current[fight.fight_id] ?? { bet_side: "", leg_price: "" };
      return [fight.fight_id, {
        ...draft,
        leg_price: draft.bet_side
          ? currentPrice(oddsByFight, fight, draft.bet_side, sportsbook)
          : "",
      }];
    })));
  }

  function selectLeg(fight, side) {
    setSaved(false);
    setManualCombinedPrice(false);
    setLegDrafts((current) => {
      const existing = current[fight.fight_id] ?? { bet_side: "", leg_price: "" };
      const nextSide = existing.bet_side === side ? "" : side;
      return {
        ...current,
        [fight.fight_id]: {
          bet_side: nextSide,
          leg_price: nextSide
            ? currentPrice(oddsByFight, fight, nextSide, ticket.sportsbook)
            : "",
        },
      };
    });
  }

  function applySuggestion(count) {
    const next = {};
    suggested.slice(0, count).forEach(({ fight, research }) => {
      next[fight.fight_id] = {
        bet_side: research.assistant_pick,
        leg_price: currentPrice(
          oddsByFight,
          fight,
          research.assistant_pick,
          ticket.sportsbook
        ),
      };
    });
    setLegDrafts(next);
    setManualCombinedPrice(false);
    setSaved(false);
  }

  async function handleSave() {
    try {
      setSaving(true);
      setSaved(false);
      setError("");
      if (ticketMode === "single") {
        const leg = selectedLegs[0];
        await saveSingleBet({
          fightId: leg.fight.fight_id,
          betSide: leg.bet_side,
          sportsbook: ticket.sportsbook,
          betPrice: displayedTicketPrice,
          stakeUnits: ticket.stakeUnits,
        });
      } else {
        await saveParlayTicket({
          ...ticket,
          ticketPrice: displayedTicketPrice,
          legs: selectedLegs.map((leg) => ({
            fight_id: leg.fight.fight_id,
            bet_side: leg.bet_side,
            leg_price: leg.leg_price,
          })),
        });
      }
      const savedType = ticketMode;
      setTicket(emptyTicket());
      setLegDrafts({});
      setManualCombinedPrice(false);
      setSaved(savedType);
      onSaved?.();
    } catch (saveError) {
      setError(saveError.message ?? "Could not save the ticket.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card parlay-entry-panel parlay-builder standalone-parlay-builder">
      <div className="parlay-builder-heading">
        <div>
          <p className="eyebrow">Clickable ticket builder</p>
          <h3>Moneyline Bet Builder</h3>
          <small>Select a book, then click one fighter for a single or several for a parlay.</small>
        </div>
        <span className="parlay-leg-count">
          {selectedLegs.length} {selectedLegs.length === 1 ? "pick" : "picks"}
        </span>
      </div>

      {!eventId ? (
        <p className="results-empty">Select an event to build a single or parlay from its moneylines.</p>
      ) : loading ? (
        <p className="results-empty">Loading card moneylines…</p>
      ) : (
        <div className="parlay-entry-body">
          <fieldset className="sportsbook-choice-control parlay-book-control">
            <legend>Sportsbook</legend>
            <div>
              {BET_SPORTSBOOKS.map((sportsbook) => (
                <button
                  type="button"
                  key={sportsbook}
                  className={ticket.sportsbook === sportsbook ? "active" : ""}
                  onClick={() => updateSportsbook(sportsbook)}
                >
                  {sportsbook}
                </button>
              ))}
            </div>
          </fieldset>

          {suggested.length >= 2 ? (
            <div className="parlay-suggestions">
              <span><Sparkles size={14} /> Imported AI combinations</span>
              <button type="button" onClick={() => applySuggestion(2)}>Best 2-leg</button>
              {suggested.length >= 3 ? <button type="button" onClick={() => applySuggestion(3)}>Best 3-leg</button> : null}
              <small>Only A-C picks without high-volatility flags qualify.</small>
            </div>
          ) : null}

          <div className="parlay-fight-grid">
            {fights.map((fight) => {
              const draft = legDrafts[fight.fight_id] ?? { bet_side: "", leg_price: "" };
              const research = researchByFight[fight.fight_id] ?? {};
              const exposed = pendingFightIds.has(Number(fight.fight_id));
              return (
                <article className={draft.bet_side ? "parlay-fight-card selected" : "parlay-fight-card"} key={fight.fight_id}>
                  <header>
                    <small>Fight {fight.fight_order ?? "—"}</small>
                    <span>
                      {research.assistant_rank ? `Tier ${research.assistant_rank}` : "Unranked"}
                      {research.assistant_volatility ? ` · ${research.assistant_volatility}` : ""}
                    </span>
                  </header>
                  <div className="parlay-fighter-choices">
                    {["fighter_a", "fighter_b"].map((side) => {
                      const price = currentPrice(oddsByFight, fight, side, ticket.sportsbook);
                      return (
                        <button
                          type="button"
                          key={side}
                          className={draft.bet_side === side ? "active" : ""}
                          onClick={() => selectLeg(fight, side)}
                        >
                          <strong>{sideLabel(fight, side)}</strong>
                          <span>{formatAmericanOdds(price)}</span>
                          {research.assistant_pick === side ? <small>AI pick</small> : null}
                        </button>
                      );
                    })}
                  </div>
                  {draft.bet_side ? (
                    <label>
                      <span>Leg odds <small>editable</small></span>
                      <input
                        type="number"
                        placeholder="-135"
                        value={draft.leg_price}
                        onChange={(event) => {
                          setManualCombinedPrice(false);
                          setLegDrafts((current) => ({
                            ...current,
                            [fight.fight_id]: { ...draft, leg_price: event.target.value },
                          }));
                        }}
                      />
                    </label>
                  ) : null}
                  {exposed ? (
                    <small className="parlay-exposure-warning"><TriangleAlert size={13} /> Already in open exposure</small>
                  ) : null}
                </article>
              );
            })}
          </div>

          <div className={`parlay-ticket-summary${ticketMode === "single" ? " single-ticket-summary" : ""}`}>
            <div className="parlay-selected-legs">
              <strong>Your ticket</strong>
              {selectedLegs.length ? selectedLegs.map((leg) => (
                <span key={leg.fight.fight_id}>
                  {sideLabel(leg.fight, leg.bet_side)} {formatAmericanOdds(leg.leg_price)}
                </span>
              )) : <small>Click one fighter for a single or several for a parlay.</small>}
            </div>
            {ticketMode === "parlay" ? (
              <label>
                <span>Ticket label <small>optional</small></span>
                <input
                  type="text"
                  placeholder="Saturday 3-leg"
                  value={ticket.ticketLabel}
                  onChange={(event) => setTicket((current) => ({ ...current, ticketLabel: event.target.value }))}
                />
              </label>
            ) : null}
            <label>
              <span>
                {ticketMode === "single" ? "Odds taken" : "Combined odds"}
                <small> editable override</small>
              </span>
              <div className="combined-odds-field">
                <input
                  type="number"
                  placeholder="+250"
                  value={displayedTicketPrice}
                  onChange={(event) => {
                    setManualCombinedPrice(true);
                    setTicket((current) => ({ ...current, ticketPrice: event.target.value }));
                  }}
                />
                {manualCombinedPrice ? (
                  <button type="button" title="Use calculated combined odds" onClick={() => setManualCombinedPrice(false)}>
                    <RotateCcw size={14} />
                  </button>
                ) : null}
              </div>
            </label>
            <label>
              <span>Stake (units)</span>
              <input
                type="number"
                min="0"
                step="0.1"
                placeholder="1.0"
                value={ticket.stakeUnits}
                onChange={(event) => setTicket((current) => ({ ...current, stakeUnits: event.target.value }))}
              />
            </label>
            <div className="parlay-payout">
              <small>Potential profit</small>
              <strong>{potentialProfit === null ? "—" : `+${potentialProfit.toFixed(2)}u`}</strong>
            </div>
          </div>

          {error ? <p className="results-error">{error}</p> : null}
          {saved ? (
            <p className="parlay-save-success">
              <Check size={15} /> {saved === "single" ? "Single" : "Parlay"} saved to Bet History.
            </p>
          ) : null}
          <button
            type="button"
            className="save-parlay-button"
            disabled={saving || loading || selectedLegs.length === 0}
            onClick={handleSave}
          >
            {saved ? <Check size={16} /> : <Save size={16} />}
            {saving
              ? "Saving…"
              : saved
                ? `${saved === "single" ? "Single" : "Parlay"} saved`
                : ticketMode === "single"
                  ? "Save single"
                  : "Save parlay"}
          </button>
        </div>
      )}
    </section>
  );
}
