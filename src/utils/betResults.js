const GRADED_STATUSES = new Set(["win", "loss"]);

function selectedFighterId(bet) {
  if (bet?.bet_side === "fighter_a") {
    return bet?.fighter_a?.fighter_id ?? null;
  }

  if (bet?.bet_side === "fighter_b") {
    return bet?.fighter_b?.fighter_id ?? null;
  }

  return null;
}

function legResult(leg) {
  if (leg?.fight_status !== "completed" || !leg?.winner_id) {
    return null;
  }

  const selectionId = selectedFighterId(leg);
  if (!selectionId) {
    return null;
  }

  return Number(selectionId) === Number(leg.winner_id) ? "win" : "loss";
}

export function getParlaySettlementSuggestion(bet) {
  if ((bet?.settlement_status ?? "pending") !== "pending") {
    return null;
  }

  const legs = Array.isArray(bet?.legs) ? bet.legs : [];
  if (legs.length < 2) {
    return null;
  }

  const losingLeg = legs.find((leg) => legResult(leg) === "loss");
  if (losingLeg) {
    return {
      status: "loss",
      confidence: "official",
      reason: `${losingLeg.selection_name ?? "A parlay leg"} lost its official result.`,
    };
  }

  const hasBookRuleLeg = legs.some((leg) =>
    ["draw", "no_contest", "cancelled"].includes(leg?.fight_status)
  );
  if (hasBookRuleLeg) {
    return null;
  }

  if (legs.every((leg) => legResult(leg) === "win")) {
    return {
      status: "win",
      confidence: "official",
      reason: "Every parlay leg is an official winner.",
    };
  }

  return null;
}

export function getOfficialSettlementSuggestion(bet) {
  if (bet?.ticket_type === "parlay") {
    return getParlaySettlementSuggestion(bet);
  }

  if ((bet?.settlement_status ?? "pending") !== "pending") {
    return null;
  }

  const fightStatus = bet?.fight_status;

  if (["draw", "no_contest", "cancelled"].includes(fightStatus)) {
    const labels = {
      draw: "The official result is a draw.",
      no_contest: "The official result is a no contest.",
      cancelled: "The bout was cancelled.",
    };

    return {
      status: "void",
      confidence: "review",
      reason: `${labels[fightStatus]} Confirm the sportsbook's settlement rule.`,
    };
  }

  if (fightStatus !== "completed" || !bet?.winner_id) {
    return null;
  }

  const selectionId = selectedFighterId(bet);
  if (!selectionId) {
    return null;
  }

  const isWinner = Number(selectionId) === Number(bet.winner_id);
  return {
    status: isWinner ? "win" : "loss",
    confidence: "official",
    reason: isWinner
      ? `${bet.selection_name ?? "Your selection"} is the official winner.`
      : `${bet.selection_name ?? "Your selection"} is not the official winner.`,
  };
}

export function suggestOfficialSettlement(bet) {
  return getOfficialSettlementSuggestion(bet)?.status ?? null;
}

function normalizedTicketValue(value) {
  return value === "" || value === undefined ? null : value;
}

export function didBetTicketChange(previous = {}, next = {}) {
  const previousStake = normalizedTicketValue(previous.stake_units);
  const nextStake = normalizedTicketValue(next.stake_units);
  const previousPrice = normalizedTicketValue(previous.bet_price);
  const nextPrice = normalizedTicketValue(next.bet_price);

  return (
    normalizedTicketValue(previous.bet_side) !== normalizedTicketValue(next.bet_side) ||
    normalizedTicketValue(previous.bet_sportsbook)?.trim?.() !== normalizedTicketValue(next.bet_sportsbook)?.trim?.() ||
    (previousPrice === null ? null : Number(previousPrice)) !== (nextPrice === null ? null : Number(nextPrice)) ||
    (previousStake === null ? null : Number(previousStake)) !== (nextStake === null ? null : Number(nextStake))
  );
}

function toFiniteNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function calculateBetProfit({ bet_price, stake_units, settlement_status }) {
  const price = toFiniteNumber(bet_price);
  const stake = Math.max(0, toFiniteNumber(stake_units));

  if (settlement_status === "loss") {
    return -stake;
  }

  if (settlement_status !== "win" || !price || !stake) {
    return 0;
  }

  return price > 0
    ? stake * (price / 100)
    : stake * (100 / Math.abs(price));
}

export function summarizeBets(bets = []) {
  return bets.reduce(
    (summary, bet) => {
      const status = bet.settlement_status ?? "pending";
      const stake = Math.max(0, toFiniteNumber(bet.stake_units));

      summary.tracked += 1;

      if (status === "pending") {
        summary.pending += 1;
        summary.pendingRisk += stake;
      } else if (status === "win") {
        summary.wins += 1;
      } else if (status === "loss") {
        summary.losses += 1;
      } else if (status === "push") {
        summary.pushes += 1;
      } else if (status === "void") {
        summary.voids += 1;
      }

      if (GRADED_STATUSES.has(status)) {
        summary.gradedRisk += stake;
        summary.netProfit += calculateBetProfit(bet);
      }

      summary.roi = summary.gradedRisk
        ? (summary.netProfit / summary.gradedRisk) * 100
        : 0;

      return summary;
    },
    {
      tracked: 0,
      pending: 0,
      wins: 0,
      losses: 0,
      pushes: 0,
      voids: 0,
      pendingRisk: 0,
      gradedRisk: 0,
      netProfit: 0,
      roi: 0,
    }
  );
}

export function summarizeBetsByPromotion(bets = []) {
  const groups = new Map();

  bets.forEach((bet) => {
    const promotion = bet.promotion_name || "Other";
    groups.set(promotion, [...(groups.get(promotion) ?? []), bet]);
  });

  return Array.from(groups, ([promotion, promotionBets]) => ({
    promotion,
    ...summarizeBets(promotionBets),
  })).sort((a, b) => b.tracked - a.tracked || a.promotion.localeCompare(b.promotion));
}

export function groupBetsByPromotionAndEvent(bets = []) {
  const promotions = new Map();

  bets.forEach((bet) => {
    const promotion = bet.promotion_name || "Other";
    const eventKey = String(bet.event_id ?? bet.event_name ?? "unknown");
    const promotionGroup = promotions.get(promotion) ?? {
      promotion,
      bets: [],
      events: new Map(),
    };
    const eventGroup = promotionGroup.events.get(eventKey) ?? {
      eventId: bet.event_id ?? null,
      eventName: bet.event_name || "Unknown event",
      eventDate: bet.event_date ?? null,
      bets: [],
    };

    promotionGroup.bets.push(bet);
    eventGroup.bets.push(bet);
    promotionGroup.events.set(eventKey, eventGroup);
    promotions.set(promotion, promotionGroup);
  });

  return Array.from(promotions.values())
    .map((promotionGroup) => ({
      promotion: promotionGroup.promotion,
      bets: promotionGroup.bets,
      summary: summarizeBets(promotionGroup.bets),
      events: Array.from(promotionGroup.events.values())
        .map((eventGroup) => ({
          ...eventGroup,
          summary: summarizeBets(eventGroup.bets),
        }))
        .sort(
          (a, b) =>
            (b.eventDate ?? "").localeCompare(a.eventDate ?? "")
            || a.eventName.localeCompare(b.eventName)
        ),
    }))
    .sort(
      (a, b) =>
        b.summary.tracked - a.summary.tracked
        || a.promotion.localeCompare(b.promotion)
    );
}
