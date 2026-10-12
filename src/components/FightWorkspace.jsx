import { Check, ChevronLeft, ChevronRight, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { getEventResearch } from "../services/eventResearchService";
import { getLatestMoneylinesForFights } from "../services/oddsService";
import {
  getFightResearch,
  saveFightResearch,
} from "../services/researchService";
import {
  calculateConsensus,
  createEmptySourcePicks,
  normalizeSourcePicks,
  VISIBLE_CONSENSUS_SOURCES,
} from "../utils/consensus";
import {
  americanOddsToImpliedProbability,
  calculateMoneylineMovement,
  formatAmericanOdds,
  getBestMoneyline,
} from "../utils/odds";
import {
  getResearchDecision,
  researchStatusForDecision,
} from "../utils/researchDecision";
import {
  extractAssistantMatchupAnalysis,
} from "../utils/assistantMatchupFacts";
import ResearchLinks from "./ResearchLinks";
import FighterDossier from "./FighterDossier";
import FightOddsDrawer from "./FightOddsDrawer";

function emptyResearch() {
  return {
    research_status: "not_started",
    fighter_a_ratings: {},
    fighter_b_ratings: {},
    matchup_notes: "",
    competition_notes: "",
    trend_notes: "",
    fighter_a_path: "",
    fighter_b_path: "",
    fighter_a_style: "",
    fighter_b_style: "",
    fighter_a_record_summary: "",
    fighter_b_record_summary: "",
    fighter_a_ko_wins: null,
    fighter_a_submission_wins: null,
    fighter_b_ko_wins: null,
    fighter_b_submission_wins: null,
    user_lean: "",
    target_price: "",
    bet_side: "",
    bet_sportsbook: "",
    bet_price: "",
    stake_units: "",
    confidence: 0,
    assistant_pick: null,
    assistant_win_probability: null,
    assistant_fair_moneyline: null,
    assistant_target_price: null,
    assistant_rank: null,
    assistant_reliability: null,
    assistant_volatility: null,
    assistant_betting_assessment: "",
    assistant_win_path: "",
    assistant_upset_path: "",
    assistant_confidence_limiter: "",
    assistant_matchup_analysis: "",
    source_picks: createEmptySourcePicks(),
  };
}

const FINISHED_FIGHT_STATUSES = new Set([
  "completed",
  "draw",
  "no_contest",
  "cancelled",
]);

function formatProbability(americanOdds) {
  const probability = americanOddsToImpliedProbability(americanOdds);
  return probability === null ? "—" : `${(probability * 100).toFixed(1)}%`;
}

function formatSnapshotTime(value) {
  if (!value) {
    return null;
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return null;
  }

  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
}

function getDisplayLine(lines, fightStatus) {
  if (FINISHED_FIGHT_STATUSES.has(fightStatus)) {
    const finalTracked = getBestMoneyline(lines, "final_tracked_odds");
    if (finalTracked) {
      return {
        line: finalTracked,
        priceField: "final_tracked_odds",
        timeField: "final_tracked_at",
        label: "Final tracked",
      };
    }
  }

  return {
    line: getBestMoneyline(lines),
    priceField: "american_odds",
    timeField: "recorded_at",
    label: FINISHED_FIGHT_STATUSES.has(fightStatus)
      ? "Latest tracked"
      : "Current",
  };
}

function cleanAnalysisLine(value) {
  return String(value ?? "")
    .replace(/^\s*[-*]\s+/, "")
    .replace(/\*\*/g, "")
    .replace(/__+/g, "")
    .trim();
}

function AssistantMatchupAnalysis({ analysis }) {
  if (!analysis) {
    return (
      <section className="assistant-matchup-panel assistant-matchup-empty">
        <div className="matchup-facts-heading">
          <div>
            <p className="eyebrow">Imported card research</p>
            <h4>Assistant Fight Analysis</h4>
          </div>
        </div>
        <p>
          Save a full-card response below the betting workspace to bring this
          fight&apos;s analysis here.
        </p>
      </section>
    );
  }

  const lines = analysis.split(/\r?\n/);

  return (
    <section className="assistant-matchup-panel">
      <div className="matchup-facts-heading">
        <div>
          <p className="eyebrow">Imported card research</p>
          <h4>Assistant Fight Analysis</h4>
        </div>
        <small>Loaded from the saved full-card response</small>
      </div>

      <div className="assistant-matchup-content">
        {lines.map((line, index) => {
          const cleaned = cleanAnalysisLine(line);
          if (!cleaned) {
            return null;
          }

          if (/^#{1,6}\s+/.test(line)) {
            return <h5 key={index}>{cleaned.replace(/^#{1,6}\s*/, "")}</h5>;
          }

          if (/^\s*[-*]\s+/.test(line)) {
            return <p className="assistant-analysis-bullet" key={index}>{cleaned}</p>;
          }

          return <p key={index}>{cleaned}</p>;
        })}
      </div>
    </section>
  );
}

function FighterPrice({ fighter, lines, fightStatus, selected, onSelect }) {
  const display = getDisplayLine(lines, fightStatus);
  const best = display.line;
  const displayedPrice = best?.[display.priceField];
  const movement = best?.snapshot_count > 1
    ? calculateMoneylineMovement(best.first_tracked_odds, displayedPrice)
    : null;

  const movementLabel = !best
    ? "No line"
    : best.snapshot_count <= 1
      ? "1 snapshot"
      : movement?.direction === "flat"
        ? "Flat"
        : `${movement.probabilityPointChange > 0 ? "+" : ""}${movement.probabilityPointChange.toFixed(1)} pp`;
  const significantMove = Math.abs(movement?.probabilityPointChange ?? 0) >= 3;

  return (
    <button
      type="button"
      className={`decision-price decision-price-choice${selected ? " decision-price-selected" : ""}`}
      aria-pressed={selected}
      onClick={onSelect}
    >
      <div className="decision-price-heading">
        <strong>{fighter.full_name}</strong>
        <small>
          {best ? `Best at ${best.sportsbook}` : "No line imported"}
        </small>
      </div>
      <div className="decision-price-values">
        <span>
          <small>First tracked</small>
          <strong>{formatAmericanOdds(best?.first_tracked_odds)}</strong>
        </span>
        <span>
          <small>{display.label}</small>
          <strong>{formatAmericanOdds(displayedPrice)}</strong>
          <small>{formatProbability(displayedPrice)} implied</small>
        </span>
      </div>
      <span
        className={`line-movement line-movement-${movement?.direction ?? "none"}${significantMove ? " line-movement-significant" : ""}`}
        title="Change in implied probability from the first tracked price"
      >
        {significantMove ? "Swing · " : ""}{movementLabel}
      </span>
      {best && (
        <small className="decision-price-updated">
          {formatSnapshotTime(best[display.timeField]) ?? "Update time unavailable"}
        </small>
      )}
    </button>
  );
}

function SportsbookComparison({
  fighterA,
  fighterB,
  fighterALines,
  fighterBLines,
  fightStatus,
}) {
  const lineKey = (line) => line.sportsbook_key || line.sportsbook;
  const aByBook = new Map(fighterALines.map((line) => [lineKey(line), line]));
  const bByBook = new Map(fighterBLines.map((line) => [lineKey(line), line]));
  const bookKeys = [...new Set([...aByBook.keys(), ...bByBook.keys()])].sort(
    (a, b) => String(a).localeCompare(String(b))
  );

  if (bookKeys.length === 0) {
    return null;
  }

  const getPrice = (line) => {
    if (!line) {
      return null;
    }

    if (
      FINISHED_FIGHT_STATUSES.has(fightStatus) &&
      line.final_tracked_odds !== null &&
      line.final_tracked_odds !== undefined
    ) {
      return line.final_tracked_odds;
    }

    return line.american_odds;
  };
  const bestA = Math.max(...fighterALines.map(getPrice).filter(Number.isFinite));
  const bestB = Math.max(...fighterBLines.map(getPrice).filter(Number.isFinite));

  return (
    <section className="sportsbook-comparison">
      <div className="sportsbook-comparison-title">
        Available sportsbook prices <span>{bookKeys.length} books</span>
      </div>
      <div className="sportsbook-lines sportsbook-chip-board">
        <div className="sportsbook-line sportsbook-line-head">
          <span>Sportsbook</span>
          <span>{fighterA.full_name}</span>
          <span>{fighterB.full_name}</span>
        </div>
        {bookKeys.map((bookKey) => {
          const lineA = aByBook.get(bookKey);
          const lineB = bByBook.get(bookKey);
          const priceA = getPrice(lineA);
          const priceB = getPrice(lineB);
          const sportsbook = lineA?.sportsbook ?? lineB?.sportsbook ?? bookKey;

          return (
            <div className="sportsbook-line" key={bookKey}>
              <strong>{sportsbook}</strong>
              <span
                className={[
                  "sportsbook-price-chip",
                  priceA === bestA ? "best-sportsbook-price" : "",
                ].filter(Boolean).join(" ")}
              >
                {formatAmericanOdds(priceA)}
              </span>
              <span
                className={[
                  "sportsbook-price-chip",
                  priceB === bestB ? "best-sportsbook-price" : "",
                ].filter(Boolean).join(" ")}
              >
                {formatAmericanOdds(priceB)}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function ConsensusSummary({ consensus, fighterA, fighterB }) {
  if (consensus.total === 0) {
    return (
      <div className="consensus-summary consensus-empty">
        Add a source name and pick to calculate consensus.
      </div>
    );
  }

  if (!consensus.leader) {
    if (consensus.counts.fighter_a === 0 && consensus.counts.fighter_b === 0) {
      return (
        <div className="consensus-summary">
          <strong>No fighter consensus</strong>
          <span>{consensus.counts.pass} pass</span>
        </div>
      );
    }

    return (
      <div className="consensus-summary">
        <strong>Split consensus</strong>
        <span>
          {fighterA.full_name}: {consensus.counts.fighter_a} · {fighterB.full_name}:{" "}
          {consensus.counts.fighter_b}
          {consensus.counts.pass ? ` · Pass: ${consensus.counts.pass}` : ""}
        </span>
      </div>
    );
  }

  const leaderName =
    consensus.leader === "fighter_a"
      ? fighterA.full_name
      : fighterB.full_name;
  const leaderCount = consensus.counts[consensus.leader];

  return (
    <div className="consensus-summary consensus-leading">
      <strong>Consensus: {leaderName}</strong>
      <span>
        {leaderCount} of {consensus.total} sources · {consensus.percentage}%
        {consensus.counts.pass ? ` · ${consensus.counts.pass} pass` : ""}
      </span>
    </div>
  );
}

export default function FightWorkspace({
  fight,
  onResearchSaved,
  onPreviousFight,
  onNextFight,
  refreshKey = 0,
}) {
  const [oddsByFight, setOddsByFight] = useState({});
  const [research, setResearch] = useState(emptyResearch);
  const [assistantCardAnalysis, setAssistantCardAnalysis] = useState("");
  const [activeResearchFighter, setActiveResearchFighter] = useState("a");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadWorkspace() {
      if (!fight?.fight_id) {
        setOddsByFight({});
        setResearch(emptyResearch());
        setAssistantCardAnalysis("");
        return;
      }

      try {
        setLoading(true);
        setError("");
        setSaved(false);

        const [oddsData, savedResearch, eventResearch] = await Promise.all([
          getLatestMoneylinesForFights([fight.fight_id]),
          getFightResearch(fight.fight_id),
          getEventResearch(fight.event_id),
        ]);

        if (!cancelled) {
          setOddsByFight(oddsData);
          const mergedResearch = {
            ...emptyResearch(),
            ...(savedResearch ?? {}),
            source_picks: normalizeSourcePicks(savedResearch?.source_picks),
          };
          if (!mergedResearch.target_price && mergedResearch.assistant_target_price) {
            mergedResearch.target_price = mergedResearch.assistant_target_price;
          }
          setResearch(mergedResearch);
          setAssistantCardAnalysis(
            eventResearch?.assistant_card_analysis ?? ""
          );
        }
      } catch (loadError) {
        console.error("Fight workspace loading error:", loadError);

        if (!cancelled) {
          setError(
            loadError.message ?? "Could not load the fight workspace."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    loadWorkspace();

    return () => {
      cancelled = true;
    };
  }, [fight, refreshKey]);

  const fighters = useMemo(() => {
    if (!fight) {
      return null;
    }

    return {
      a: fight.fighter_a,
      b: fight.fighter_b,
    };
  }, [fight]);

  if (!fight?.fighter_a || !fight?.fighter_b) {
    return (
      <section className="card fight-workspace-panel workspace-empty">
        <div>
          <p className="eyebrow">Matchup research</p>
          <h2>Fight Workspace</h2>
          <p>Select a matchup from the fight card to begin your read.</p>
        </div>
      </section>
    );
  }

  const fightOdds = oddsByFight[fight.fight_id] ?? {};
  const fighterAOdds = fightOdds[fight.fighter_a.fighter_id] ?? [];
  const fighterBOdds = fightOdds[fight.fighter_b.fighter_id] ?? [];
  const activeFighter = fighters[activeResearchFighter];
  const activeOpponent =
    fighters[activeResearchFighter === "a" ? "b" : "a"];
  const consensus = calculateConsensus(research.source_picks);
  const assistantMatchupAnalysis = extractAssistantMatchupAnalysis(
    assistantCardAnalysis,
    fight
  );
  const displayedAssistantAnalysis =
    research.assistant_matchup_analysis?.trim() || assistantMatchupAnalysis;

  function updateField(field, value) {
    setSaved(false);
    setResearch((current) => ({ ...current, [field]: value }));
  }

  function updateResearchDecision(value) {
    setSaved(false);
    setResearch((current) => ({
      ...current,
      research_status: researchStatusForDecision(value),
      user_lean: value,
    }));
  }

  function updateSourcePick(index, field, value) {
    setSaved(false);
    setResearch((current) => ({
      ...current,
      source_picks: normalizeSourcePicks(current.source_picks).map(
        (sourcePick, sourceIndex) =>
          sourceIndex === index
            ? { ...sourcePick, [field]: value }
            : sourcePick
      ),
    }));
  }

  async function handleSave(advance = false) {
    try {
      setSaving(true);
      setError("");
      const savedResearch = await saveFightResearch(fight.fight_id, research);
      setResearch((current) => ({ ...current, ...savedResearch }));
      setSaved(true);
      onResearchSaved?.();
      if (advance) onNextFight?.();
    } catch (saveError) {
      console.error("Fight research saving error:", saveError);

      if (saveError.partialData) {
        setResearch((current) => ({
          ...current,
          ...saveError.partialData,
          source_picks: normalizeSourcePicks(
            saveError.partialData.source_picks ?? current.source_picks
          ),
        }));
      }

      setError(
        saveError.message ?? "Could not save this fight research."
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card fight-workspace-panel">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">Fight view</p>
          <h2>
            {fight.fighter_a.full_name}
            <span> vs </span>
            {fight.fighter_b.full_name}
          </h2>
          <p className="workspace-meta">
            {fight.bout_type
              ?? fight.weight_classes?.name
              ?? "Weight class unavailable"}
            <span>•</span>
            {fight.scheduled_rounds ?? 3} rounds
            {fight.is_title_fight ? <><span>•</span>Title fight</> : null}
          </p>
        </div>

        <div className="workspace-header-actions">
          <div className="fight-navigation" aria-label="Fight navigation">
            <button type="button" onClick={onPreviousFight} disabled={!onPreviousFight}>
              <ChevronLeft size={15} /> Previous
            </button>
            <button type="button" onClick={onNextFight} disabled={!onNextFight}>
              Next <ChevronRight size={15} />
            </button>
          </div>
          <fieldset className="research-decision-control">
            <legend>Research decision</legend>
            <div>
              {[
                { value: "", label: "Not started" },
                { value: "fighter_a", label: fight.fighter_a.full_name },
                { value: "fighter_b", label: fight.fighter_b.full_name },
                { value: "pass", label: "Pass" },
              ].map((option) => (
                <button
                  type="button"
                  key={option.value || "not-started"}
                  className={getResearchDecision(research) === option.value ? "active" : ""}
                  aria-pressed={getResearchDecision(research) === option.value}
                  onClick={() => updateResearchDecision(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </fieldset>
        </div>
      </header>

      {loading && <p className="workspace-notice">Loading saved research…</p>}
      {error && <p className="workspace-error">{error}</p>}

      <div className="workspace-grid">
        <main className="workspace-section analysis-panel">
          <div className="mini-heading">
            <div>
              <p className="eyebrow">Your independent read</p>
              <h3>Matchup Assessment</h3>
            </div>
          </div>

          <details className="research-links-drawer">
            <summary>Research sources</summary>
            <div className="research-links-drawer-content">
              <div className="fighter-toggle">
                <button
                  type="button"
                  className={activeResearchFighter === "a" ? "active" : ""}
                  onClick={() => setActiveResearchFighter("a")}
                >
                  {fight.fighter_a.full_name.split(" ").at(-1)}
                </button>
                <button
                  type="button"
                  className={activeResearchFighter === "b" ? "active" : ""}
                  onClick={() => setActiveResearchFighter("b")}
                >
                  {fight.fighter_b.full_name.split(" ").at(-1)}
                </button>
              </div>
              <ResearchLinks
                fighter={activeFighter}
                opponent={activeOpponent}
                promotionName={fight.events?.promotions?.name}
              />
            </div>
          </details>

          <FighterDossier fight={fight} research={research} />

          <AssistantMatchupAnalysis analysis={displayedAssistantAnalysis} />

          <section className="outside-picks-panel">
            <div className="mini-heading outside-picks-heading">
              <div>
                <p className="eyebrow">Outside opinions</p>
                <h3>Source Picks</h3>
              </div>
              <span className="rating-key">Up to 3 sources</span>
            </div>

            <div className="source-picks-table">
              <div className="source-picks-head">
                <span>Source</span>
                <span>Pick</span>
              </div>
              {normalizeSourcePicks(research.source_picks)
                .slice(0, VISIBLE_CONSENSUS_SOURCES)
                .map(
                (sourcePick, index) => (
                    <div className="source-picks-row" key={index}>
                      <input
                        type="text"
                        aria-label={`Source ${index + 1} name`}
                        placeholder={`Source ${index + 1}`}
                        value={sourcePick.label}
                        onChange={(event) =>
                          updateSourcePick(index, "label", event.target.value)
                        }
                      />
                      <div className="source-pick-buttons" aria-label={`Source ${index + 1} pick`}>
                        {[
                          { value: "fighter_a", label: fight.fighter_a.full_name.split(" ").at(-1) },
                          { value: "fighter_b", label: fight.fighter_b.full_name.split(" ").at(-1) },
                          { value: "pass", label: "Pass" },
                        ].map((option) => (
                          <button
                            type="button"
                            key={option.value}
                            className={sourcePick.pick === option.value ? "active" : ""}
                            aria-pressed={sourcePick.pick === option.value}
                            onClick={() => updateSourcePick(
                              index,
                              "pick",
                              sourcePick.pick === option.value ? "" : option.value
                            )}
                          >
                            {option.label}
                          </button>
                        ))}
                      </div>
                    </div>
                )
              )}
            </div>

            <ConsensusSummary
              consensus={consensus}
              fighterA={fight.fighter_a}
              fighterB={fight.fighter_b}
            />
          </section>

        </main>

        <aside className="workspace-section decision-panel">
          <div className="mini-heading">
            <div>
              <p className="eyebrow">Price & action</p>
              <h3>Betting Decision</h3>
            </div>
            <FightOddsDrawer />
          </div>

          <div className="price-board">
            <FighterPrice
              fighter={fight.fighter_a}
              lines={fighterAOdds}
              fightStatus={fight.fight_status}
              selected={getResearchDecision(research) === "fighter_a"}
              onSelect={() => updateResearchDecision("fighter_a")}
            />
            <FighterPrice
              fighter={fight.fighter_b}
              lines={fighterBOdds}
              fightStatus={fight.fight_status}
              selected={getResearchDecision(research) === "fighter_b"}
              onSelect={() => updateResearchDecision("fighter_b")}
            />
          </div>

          <p className="price-board-caption">
            First tracked is the earliest price saved by this dashboard at the
            sportsbook showing the best available line. It is not claimed as the
            sportsbook&apos;s true opener. Implied probability includes vig.
          </p>

          <SportsbookComparison
            fighterA={fight.fighter_a}
            fighterB={fight.fighter_b}
            fighterALines={fighterAOdds}
            fighterBLines={fighterBOdds}
            fightStatus={fight.fight_status}
          />

          <section className="assistant-price-guidance">
            <div>
              <small>Imported AI decision</small>
              <strong>
                {research.assistant_pick === "fighter_a"
                  ? fight.fighter_a.full_name
                  : research.assistant_pick === "fighter_b"
                    ? fight.fighter_b.full_name
                    : research.assistant_pick === "pass"
                      ? "Pass"
                      : "Run fresh card research"}
              </strong>
              <span>
                {research.assistant_win_probability
                  ? `${research.assistant_win_probability}% · fair ${formatAmericanOdds(research.assistant_fair_moneyline)}`
                  : "Probability and fair line not imported yet"}
              </span>
            </div>
            <div className="assistant-price-tags">
              <span>Tier {research.assistant_rank ?? "—"}</span>
              <span>{research.assistant_reliability ?? "—"} reliability</span>
              <span>{research.assistant_volatility ?? "—"} volatility</span>
            </div>
            {research.assistant_betting_assessment ? (
              <p>{research.assistant_betting_assessment}</p>
            ) : null}
          </section>

          <label className="decision-field">
            <span>
              Target moneyline
              {research.assistant_target_price ? (
                <small> AI buy-at {formatAmericanOdds(research.assistant_target_price)}</small>
              ) : null}
            </span>
            <input
              type="number"
              placeholder="e.g. -135"
              value={research.target_price ?? ""}
              onChange={(event) => updateField("target_price", event.target.value)}
            />
          </label>

          <fieldset className="confidence-field">
            <legend>Confidence</legend>
            <div>
              {[1, 2, 3, 4, 5].map((rating) => (
                <button
                  type="button"
                  key={rating}
                  className={research.confidence === rating ? "active" : ""}
                  aria-pressed={research.confidence === rating}
                  onClick={() => updateField("confidence", rating)}
                >
                  {rating}
                </button>
              ))}
            </div>
          </fieldset>

          <div className="save-research-actions">
            <button
              type="button"
              className="save-research-button"
              disabled={saving || loading}
              onClick={() => handleSave(false)}
            >
              {saved ? <Check size={17} /> : <Save size={17} />}
              {saving ? "Saving…" : saved ? "Research saved" : "Save research"}
            </button>
            {onNextFight ? (
              <button
                type="button"
                className="save-next-button"
                disabled={saving || loading}
                onClick={() => handleSave(true)}
              >
                Save &amp; next <ChevronRight size={16} />
              </button>
            ) : null}
          </div>

          <p className="save-caption">
            Your notes stay attached to this matchup and return whenever you reopen it.
          </p>
        </aside>
      </div>
    </section>
  );
}
