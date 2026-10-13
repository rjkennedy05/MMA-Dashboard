function normalizedFighterName(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "");
}

export function fightMatchupKey(fight) {
  const names = [
    normalizedFighterName(fight?.fighter_a?.full_name),
    normalizedFighterName(fight?.fighter_b?.full_name),
  ];
  if (names.every(Boolean)) {
    return `names:${names.sort().join("::")}`;
  }

  const fighterIds = [fight?.fighter_a_id, fight?.fighter_b_id]
    .map(Number)
    .filter(Number.isFinite)
    .sort((a, b) => a - b);
  return fighterIds.length === 2
    ? `ids:${fighterIds.join("::")}`
    : `fight:${fight?.fight_id ?? "unknown"}`;
}

function displayPriority(fight) {
  const active = fight?.fight_status === "cancelled" ? 0 : 1;
  const complete = ["completed", "draw", "no_contest"].includes(fight?.fight_status)
    ? 1
    : 0;
  const detail = [
    fight?.winner_id,
    fight?.method,
    fight?.weight_class_id,
    fight?.weight_classes?.name,
  ].filter(Boolean).length;
  return { active, complete, detail };
}

function preferFight(left, right) {
  const leftPriority = displayPriority(left);
  const rightPriority = displayPriority(right);
  for (const field of ["active", "complete", "detail"]) {
    if (leftPriority[field] !== rightPriority[field]) {
      return leftPriority[field] > rightPriority[field] ? left : right;
    }
  }
  return Number(left?.fight_id ?? Infinity) <= Number(right?.fight_id ?? Infinity)
    ? left
    : right;
}

export function dedupeEventFights(fights = []) {
  const byMatchup = new Map();
  for (const fight of Array.isArray(fights) ? fights : []) {
    const key = fightMatchupKey(fight);
    const existing = byMatchup.get(key);
    byMatchup.set(key, existing ? preferFight(existing, fight) : fight);
  }
  return [...byMatchup.values()].sort((left, right) =>
    Number(left?.fight_order ?? 999) - Number(right?.fight_order ?? 999)
    || Number(left?.fight_id ?? 0) - Number(right?.fight_id ?? 0)
  );
}
