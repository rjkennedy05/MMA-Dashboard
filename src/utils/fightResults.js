const OFFICIAL_STATUSES = new Set(["completed", "draw", "no_contest"]);

export function formatFightStatus(status) {
  const labels = {
    scheduled: "Scheduled",
    upcoming: "Scheduled",
    in_progress: "Live",
    live: "Live",
    completed: "Completed",
    cancelled: "Cancelled",
    draw: "Draw",
    no_contest: "No contest",
  };
  return labels[status] ?? "Status unavailable";
}

function formatFinishTime(seconds) {
  if (!Number.isFinite(Number(seconds))) {
    return null;
  }
  const total = Number(seconds);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function getOfficialResult(fight) {
  if (!OFFICIAL_STATUSES.has(fight?.fight_status)) {
    return null;
  }

  const winner =
    Number(fight?.winner_id) === Number(fight?.fighter_a_id)
      ? fight?.fighter_a?.full_name
      : Number(fight?.winner_id) === Number(fight?.fighter_b_id)
        ? fight?.fighter_b?.full_name
        : null;

  const headline =
    fight.fight_status === "draw"
      ? "Draw"
      : fight.fight_status === "no_contest"
        ? "No contest"
        : winner
          ? `${winner} won`
          : "Completed";

  const details = [];
  if (fight.method) details.push(fight.method);
  if (fight.finish_round) details.push(`R${fight.finish_round}`);
  const finishTime = formatFinishTime(fight.finish_time_seconds);
  if (finishTime) details.push(finishTime);

  return {
    headline,
    details: details.join(" • "),
  };
}
