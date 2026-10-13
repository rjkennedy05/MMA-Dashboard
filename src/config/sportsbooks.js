export const BET_SPORTSBOOKS = ["FD", "DK", "B365", "HR", "BO"];

const SPORTSBOOK_ALIASES = {
  FD: ["fd", "fanduel", "fanduel sportsbook"],
  DK: ["dk", "draftkings", "draftkings sportsbook"],
  B365: ["b365", "bet365"],
  HR: ["hr", "hardrockbet", "hard rock bet"],
  BO: ["bo", "betonlineag", "betonline.ag", "betonline"],
};

function compactBookName(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

export function normalizeSportsbook(value) {
  const compact = compactBookName(value);

  for (const [shortName, aliases] of Object.entries(SPORTSBOOK_ALIASES)) {
    if (
      compact === compactBookName(shortName)
      || aliases.some((alias) => compact === compactBookName(alias))
    ) {
      return shortName;
    }
  }

  return compact;
}

export function sportsbookMatches(line, sportsbook) {
  const target = normalizeSportsbook(sportsbook);
  return [line?.sportsbook_key, line?.sportsbook]
    .some((value) => normalizeSportsbook(value) === target);
}
