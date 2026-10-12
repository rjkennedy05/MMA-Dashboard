export const RESEARCH_DECISIONS = new Set([
  "fighter_a",
  "fighter_b",
  "pass",
]);

export function getResearchDecision(research) {
  const lean = research?.user_lean ?? "";

  if (RESEARCH_DECISIONS.has(lean)) {
    return lean;
  }

  return research?.research_status === "pass" ? "pass" : "";
}

export function researchStatusForDecision(decision) {
  if (decision === "pass") {
    return "pass";
  }

  if (decision === "fighter_a" || decision === "fighter_b") {
    return "initial_lean";
  }

  return "not_started";
}

export function fighterDecisionClass(decision, fighterSide) {
  if (decision === "pass") {
    return "fighter-pass-highlight";
  }

  return decision === fighterSide ? "fighter-lean-highlight" : "";
}
