export function americanOddsToImpliedProbability(americanOdds) {
  const odds = Number(americanOdds);

  if (!Number.isFinite(odds) || odds === 0) {
    return null;
  }

  return odds > 0
    ? 100 / (odds + 100)
    : Math.abs(odds) / (Math.abs(odds) + 100);
}

export function americanOddsToDecimal(americanOdds) {
  const odds = Number(americanOdds);
  if (!Number.isFinite(odds) || (odds > -100 && odds < 100)) return null;
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

export function decimalOddsToAmerican(decimalOdds) {
  const odds = Number(decimalOdds);
  if (!Number.isFinite(odds) || odds <= 1) return null;
  return Math.round(odds >= 2 ? (odds - 1) * 100 : -100 / (odds - 1));
}

export function combineAmericanOdds(prices = []) {
  const decimals = prices.map(americanOddsToDecimal);
  if (decimals.length < 2 || decimals.some((value) => value === null)) return null;
  return decimalOddsToAmerican(decimals.reduce((product, value) => product * value, 1));
}

export function formatAmericanOdds(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const odds = Number(value);
  if (!Number.isFinite(odds) || odds === 0) {
    return "—";
  }

  return odds > 0 ? `+${odds}` : `${odds}`;
}

export function getBestMoneyline(lines, priceField = "american_odds") {
  return (Array.isArray(lines) ? lines : []).reduce((best, current) => {
    const price = Number(current?.[priceField]);
    const bestPrice = Number(best?.[priceField]);

    if (!Number.isFinite(price) || price === 0) {
      return best;
    }

    if (!best || !Number.isFinite(bestPrice) || price > bestPrice) {
      return current;
    }

    return best;
  }, null);
}

function compareSnapshots(a, b) {
  const aTime = Date.parse(a.recorded_at ?? "");
  const bTime = Date.parse(b.recorded_at ?? "");
  const timeComparison =
    (Number.isFinite(aTime) ? aTime : 0) -
    (Number.isFinite(bTime) ? bTime : 0);

  if (timeComparison !== 0) {
    return timeComparison;
  }

  return Number(a.odds_id ?? 0) - Number(b.odds_id ?? 0);
}

export function buildMoneylineHistory(rows) {
  const seriesBySportsbook = new Map();

  for (const row of Array.isArray(rows) ? rows : []) {
    const identity = row.sportsbook_key || row.sportsbook || "unknown";
    const key = [row.fight_id, row.fighter_id, identity].join(":");

    if (!seriesBySportsbook.has(key)) {
      seriesBySportsbook.set(key, []);
    }

    seriesBySportsbook.get(key).push(row);
  }

  const grouped = {};

  for (const snapshots of seriesBySportsbook.values()) {
    snapshots.sort(compareSnapshots);

    const first = snapshots[0];
    const latest = snapshots[snapshots.length - 1];
    const commenceTime = [...snapshots]
      .reverse()
      .find((snapshot) => snapshot.market_commence_time)
      ?.market_commence_time ?? null;

    const preFightSnapshots = commenceTime
      ? snapshots.filter(
          (snapshot) =>
            Number.isFinite(Date.parse(snapshot.recorded_at ?? "")) &&
            Date.parse(snapshot.recorded_at) <= Date.parse(commenceTime)
        )
      : [];
    const finalTracked = preFightSnapshots.at(-1) ?? null;
    const fightId = latest.fight_id;
    const fighterId = latest.fighter_id;

    if (!grouped[fightId]) {
      grouped[fightId] = {};
    }

    if (!grouped[fightId][fighterId]) {
      grouped[fightId][fighterId] = [];
    }

    grouped[fightId][fighterId].push({
      ...latest,
      first_tracked_odds: first.american_odds,
      first_tracked_at: first.recorded_at,
      opening_odds: first.american_odds,
      opening_recorded_at: first.recorded_at,
      snapshot_count: snapshots.length,
      market_commence_time: commenceTime,
      final_tracked_odds: finalTracked?.american_odds ?? null,
      final_tracked_at: finalTracked?.recorded_at ?? null,
    });
  }

  for (const fight of Object.values(grouped)) {
    for (const fighterOdds of Object.values(fight)) {
      fighterOdds.sort((a, b) =>
        (a.sportsbook ?? "").localeCompare(b.sportsbook ?? "")
      );
    }
  }

  return grouped;
}

export function calculateMoneylineMovement(openingOdds, currentOdds) {
  const openingProbability = americanOddsToImpliedProbability(openingOdds);
  const currentProbability = americanOddsToImpliedProbability(currentOdds);

  if (openingProbability === null || currentProbability === null) {
    return null;
  }

  const probabilityPointChange =
    (currentProbability - openingProbability) * 100;

  if (Math.abs(probabilityPointChange) < 0.05) {
    return {
      direction: "flat",
      probabilityPointChange: 0,
    };
  }

  return {
    direction: probabilityPointChange > 0 ? "shortened" : "drifted",
    probabilityPointChange,
  };
}
