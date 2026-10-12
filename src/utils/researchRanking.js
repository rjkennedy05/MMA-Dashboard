import {
  americanOddsToImpliedProbability,
  calculateMoneylineMovement,
  getBestMoneyline,
} from "./odds.js";

const RANK_ORDER = { A: 0, B: 1, C: 2, D: 3 };

export function selectedFighterForSide(fight, side) {
  if (side === "fighter_a") return fight?.fighter_a ?? null;
  if (side === "fighter_b") return fight?.fighter_b ?? null;
  return null;
}

export function buildResearchBoardRows(researchRows = [], oddsByFight = {}) {
  return researchRows.map((research) => {
    const fight = research.fight;
    const assistantFighter = selectedFighterForSide(fight, research.assistant_pick);
    const userFighter = selectedFighterForSide(fight, research.user_lean);
    const selectedFighter = assistantFighter ?? userFighter;
    const lines = selectedFighter
      ? oddsByFight?.[fight.fight_id]?.[selectedFighter.fighter_id] ?? []
      : [];
    const bestLine = getBestMoneyline(lines);
    const currentPrice = Number(bestLine?.american_odds);
    const probability = Number(research.assistant_win_probability);
    const implied = americanOddsToImpliedProbability(currentPrice);
    const edge = Number.isFinite(probability) && implied !== null
      ? probability - implied * 100
      : null;
    const movement = bestLine?.snapshot_count > 1
      ? calculateMoneylineMovement(bestLine.first_tracked_odds, currentPrice)
      : null;
    const target = Number(research.target_price || research.assistant_target_price);

    return {
      ...research,
      fight,
      event: fight.events,
      assistantFighter,
      userFighter,
      selectedFighter,
      bestLine,
      currentPrice: Number.isFinite(currentPrice) ? currentPrice : null,
      edgeProbabilityPoints: edge === null ? null : Number(edge.toFixed(1)),
      movement,
      significantMove: Math.abs(movement?.probabilityPointChange ?? 0) >= 3,
      targetPrice: Number.isFinite(target) ? target : null,
      targetReached: Number.isFinite(target) && Number.isFinite(currentPrice)
        ? currentPrice >= target
        : false,
    };
  }).sort((left, right) => {
    const leftRank = RANK_ORDER[left.assistant_rank] ?? 9;
    const rightRank = RANK_ORDER[right.assistant_rank] ?? 9;
    return leftRank - rightRank
      || (right.edgeProbabilityPoints ?? -999) - (left.edgeProbabilityPoints ?? -999)
      || (right.assistant_win_probability ?? 0) - (left.assistant_win_probability ?? 0)
      || (left.event?.event_date ?? "").localeCompare(right.event?.event_date ?? "")
      || (left.fight?.fight_order ?? 0) - (right.fight?.fight_order ?? 0);
  }).map((row, index) => ({ ...row, overallRank: index + 1 }));
}

export function rankLabel(rank) {
  return rank && RANK_ORDER[rank] !== undefined ? rank : "—";
}
