// Keep the historical five-slot payload shape so old Source 4/5 notes are not
// erased when a matchup is saved. The professional workspace intentionally
// shows and scores only the first three sources.
export const STORED_CONSENSUS_SOURCES = 5;
export const VISIBLE_CONSENSUS_SOURCES = 3;

export function createEmptySourcePicks() {
  return Array.from({ length: STORED_CONSENSUS_SOURCES }, () => ({
    label: "",
    pick: "",
  }));
}

export function normalizeSourcePicks(sourcePicks) {
  const picks = Array.isArray(sourcePicks) ? sourcePicks : [];

  return createEmptySourcePicks().map((emptyPick, index) => ({
    ...emptyPick,
    ...(picks[index] ?? {}),
  }));
}

export function calculateConsensus(sourcePicks) {
  const completedPicks = normalizeSourcePicks(sourcePicks)
    .slice(0, VISIBLE_CONSENSUS_SOURCES)
    .filter(
    ({ label, pick }) => label.trim() && pick
  );

  const counts = completedPicks.reduce(
    (totals, { pick }) => ({
      ...totals,
      [pick]: (totals[pick] ?? 0) + 1,
    }),
    { fighter_a: 0, fighter_b: 0, pass: 0 }
  );

  const total = completedPicks.length;
  const leadingCount = Math.max(counts.fighter_a, counts.fighter_b);
  let leader = "";

  if (leadingCount > 0 && counts.fighter_a !== counts.fighter_b) {
    leader = counts.fighter_a > counts.fighter_b ? "fighter_a" : "fighter_b";
  }

  return {
    counts,
    leader,
    percentage: leader ? Math.round((counts[leader] / total) * 100) : 0,
    total,
  };
}
