export function formatHeight(inches) {
  const value = Number(inches);
  if (!Number.isFinite(value) || value <= 0) {
    return "—";
  }
  const rounded = Math.round(value);
  return `${Math.floor(rounded / 12)}' ${rounded % 12}"`;
}

export function formatReach(inches) {
  const value = Number(inches);
  return Number.isFinite(value) && value > 0 ? `${Math.round(value)}"` : "—";
}

export function fighterAge(fighter, now = new Date()) {
  const snapshot = Number(fighter?.age_snapshot);
  if (Number.isInteger(snapshot) && snapshot > 0) {
    return snapshot;
  }

  const birthDate = new Date(fighter?.date_of_birth ?? "");
  if (Number.isNaN(birthDate.getTime()) || Number.isNaN(now.getTime())) {
    return null;
  }
  let age = now.getUTCFullYear() - birthDate.getUTCFullYear();
  const beforeBirthday =
    now.getUTCMonth() < birthDate.getUTCMonth() ||
    (now.getUTCMonth() === birthDate.getUTCMonth() &&
      now.getUTCDate() < birthDate.getUTCDate());
  if (beforeBirthday) {
    age -= 1;
  }
  return age > 0 ? age : null;
}

export function profileCoverage(fighter) {
  const values = [
    fighter?.record_summary,
    fighterAge(fighter),
    fighter?.height_inches,
    fighter?.reach_inches,
    fighter?.stance,
    fighter?.nationality,
  ];
  const available = values.filter(
    (value) => value !== null && value !== undefined && value !== ""
  ).length;
  return { available, total: values.length };
}
