export function historyCoverageLabel(coverage) {
  const status = coverage?.coverage_status;
  if (status === "confirmed_debut") return "Professional debut indicated";
  if (status === "partial_history") return "Partial public fight history recovered";
  if (status === "regional_history_unavailable") return "Prior record found; bout details unavailable";
  if (status === "history_unavailable") return "History unavailable after all automatic checks";
  if (status === "needs_review") return "Identity match needs review";
  if (status === "linked_history") return "History linked from stored identity";
  if (status === "fallback_history") return "Fallback history recovered";
  if (status === "complete") return "Connected history available";
  if (status === "pending") return "Automatic history check pending";
  return "Automatic history check has not run yet";
}

export function historyEmptyMessage(coverage) {
  if (coverage?.coverage_note) return coverage.coverage_note;
  return "Automatic history maintenance has not checked this fighter yet.";
}

export function historyRunLabel(run) {
  if (!run) return "Not run";
  if (run.status === "success") return "Checked";
  if (run.status === "partial") return "Review needed";
  if (run.status === "failed") return "Failed";
  return "Running";
}
