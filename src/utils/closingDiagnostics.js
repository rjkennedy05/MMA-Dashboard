import { sportsbookMatches } from "../config/sportsbooks.js";
import { americanOddsToImpliedProbability } from "./odds.js";

const FLAT_THRESHOLD = 0.05;

function selectedFighterId(leg) {
  if (leg?.bet_side === "fighter_a") {
    return leg?.fighter_a?.fighter_id ?? leg?.fighter_a_id ?? null;
  }

  if (leg?.bet_side === "fighter_b") {
    return leg?.fighter_b?.fighter_id ?? leg?.fighter_b_id ?? null;
  }

  return null;
}

function closingSamplesForBet(bet) {
  if (bet?.ticket_type === "parlay") {
    return (bet.legs ?? []).map((leg) => ({
      ...leg,
      sportsbook: bet.bet_sportsbook,
      takenPrice: leg.leg_price,
      ticketType: "parlay_leg",
    }));
  }

  return [{
    ...bet,
    sportsbook: bet?.bet_sportsbook,
    takenPrice: bet?.bet_price,
    ticketType: "single",
  }];
}

export function buildTrackedCloseDiagnostics(bets = [], oddsByFight = {}) {
  const samples = [];

  for (const bet of bets) {
    for (const candidate of closingSamplesForBet(bet)) {
      const fighterId = selectedFighterId(candidate);
      const takenPrice = Number(candidate.takenPrice);
      const lines = oddsByFight?.[candidate.fight_id]?.[fighterId] ?? [];
      const sameBook = lines.find((line) =>
        sportsbookMatches(line, candidate.sportsbook)
      );
      const finalTrackedPrice = Number(sameBook?.final_tracked_odds);
      const takenProbability = americanOddsToImpliedProbability(takenPrice);
      const finalProbability = americanOddsToImpliedProbability(finalTrackedPrice);

      if (
        !fighterId
        || takenProbability === null
        || finalProbability === null
      ) {
        continue;
      }

      const probabilityPointChange =
        (finalProbability - takenProbability) * 100;

      samples.push({
        ticket_type: candidate.ticketType,
        probability_point_change: probabilityPointChange,
        result:
          probabilityPointChange > FLAT_THRESHOLD
            ? "beat_tracked_close"
            : probabilityPointChange < -FLAT_THRESHOLD
              ? "worse_than_tracked_close"
              : "flat",
      });
    }
  }

  const beatCount = samples.filter(
    (sample) => sample.result === "beat_tracked_close"
  ).length;
  const worseCount = samples.filter(
    (sample) => sample.result === "worse_than_tracked_close"
  ).length;
  const flatCount = samples.length - beatCount - worseCount;
  const average = samples.length
    ? samples.reduce(
        (sum, sample) => sum + sample.probability_point_change,
        0
      ) / samples.length
    : 0;

  return {
    label: "Tracked close movement",
    comparison_count: samples.length,
    beat_tracked_close_count: beatCount,
    worse_than_tracked_close_count: worseCount,
    flat_count: flatCount,
    beat_rate_percent: samples.length
      ? Number(((beatCount / samples.length) * 100).toFixed(1))
      : null,
    average_probability_point_change: Number(average.toFixed(2)),
    sample_guidance:
      samples.length < 20
        ? "Small sample: use only as a descriptive price-discipline check; do not recalibrate picks from it."
        : samples.length < 50
          ? "Developing sample: use as a secondary process check, not a matchup override."
          : "Established sample: use as a meaningful price-discipline diagnostic while keeping matchup evidence primary.",
    terminology:
      "Final tracked is the dashboard's last saved pre-fight price at the same sportsbook, not a guaranteed market closing line.",
  };
}

export function summarizeLeanAccuracy(rows = []) {
  const outcomes = rows.filter((row) => {
    if (!row?.winner_id) return false;
    return row?.user_lean === "fighter_a" || row?.user_lean === "fighter_b";
  });
  const wins = outcomes.filter((row) => {
    const selectedId = row.user_lean === "fighter_a"
      ? row.fighter_a_id
      : row.fighter_b_id;
    return Number(selectedId) === Number(row.winner_id);
  }).length;
  const losses = outcomes.length - wins;

  return {
    completed_lean_count: outcomes.length,
    wins,
    losses,
    accuracy_percent: outcomes.length
      ? Number(((wins / outcomes.length) * 100).toFixed(1))
      : null,
    sample_guidance:
      outcomes.length < 20
        ? "Small sample: report it, but do not chase recent outcomes or broadly rewrite the handicapping process."
        : "Use as a calibration check alongside price discipline and matchup-specific evidence.",
  };
}

function summarizeSettledTickets(bets = []) {
  const settled = bets.filter((bet) => ["win", "loss"].includes(bet.settlement_status));
  const wins = settled.filter((bet) => bet.settlement_status === "win").length;
  const risk = settled.reduce((sum, bet) => sum + (Number(bet.stake_units) || 0), 0);
  const profit = settled.reduce((sum, bet) => {
    const stake = Number(bet.stake_units) || 0;
    const price = Number(bet.bet_price) || 0;
    if (bet.settlement_status === "loss") return sum - stake;
    return sum + (price > 0 ? stake * price / 100 : stake * 100 / Math.abs(price));
  }, 0);
  return {
    count: settled.length,
    wins,
    losses: settled.length - wins,
    win_rate_percent: settled.length ? Number((wins / settled.length * 100).toFixed(1)) : null,
    net_units: Number(profit.toFixed(2)),
    roi_percent: risk ? Number((profit / risk * 100).toFixed(1)) : null,
  };
}

export function buildProcessScorecard(bets = [], closeMovement = null, leanAccuracy = null) {
  const singles = bets.filter((bet) => bet.ticket_type === "single");
  const parlays = bets.filter((bet) => bet.ticket_type === "parlay");
  const confidenceGroups = [1, 2, 3, 4, 5].flatMap((confidence) => {
    const group = summarizeSettledTickets(
      singles.filter((bet) => Number(bet.confidence) === confidence)
    );
    return group.count ? [{ confidence, ...group }] : [];
  });
  const rankGroups = ["A", "B", "C", "D"].flatMap((rank) => {
    const group = summarizeSettledTickets(
      singles.filter((bet) => bet.assistant_rank === rank)
    );
    return group.count ? [{ rank, ...group }] : [];
  });

  return {
    lean_accuracy: leanAccuracy,
    tracked_close_movement: closeMovement,
    singles: summarizeSettledTickets(singles),
    parlays: summarizeSettledTickets(parlays),
    confidence_groups: confidenceGroups,
    assistant_rank_groups: rankGroups,
    guidance: "Judge the process with prediction calibration, price discipline, and risk concentration together. A single result never proves a good or bad read.",
  };
}
