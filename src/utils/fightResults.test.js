import assert from "node:assert/strict";
import test from "node:test";

import { formatFightStatus, getOfficialResult } from "./fightResults.js";

test("formats an official winner, method, round, and time", () => {
  const result = getOfficialResult({
    fight_status: "completed",
    fighter_a_id: 1,
    fighter_b_id: 2,
    winner_id: 2,
    fighter_a: { full_name: "Uros Medic" },
    fighter_b: { full_name: "Daniel Rodriguez" },
    method: "Decision - Unanimous",
    finish_round: 3,
    finish_time_seconds: 300,
  });

  assert.equal(result.headline, "Daniel Rodriguez won");
  assert.equal(result.details, "Decision - Unanimous • R3 • 5:00");
});

test("distinguishes live, cancelled, draw, and no-contest statuses", () => {
  assert.equal(formatFightStatus("in_progress"), "Live");
  assert.equal(formatFightStatus("cancelled"), "Cancelled");
  assert.equal(getOfficialResult({ fight_status: "draw" }).headline, "Draw");
  assert.equal(
    getOfficialResult({ fight_status: "no_contest" }).headline,
    "No contest"
  );
});
