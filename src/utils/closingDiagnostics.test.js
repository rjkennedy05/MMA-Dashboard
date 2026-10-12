import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTrackedCloseDiagnostics,
  summarizeLeanAccuracy,
} from "./closingDiagnostics.js";

test("compares singles and parlay legs with the same sportsbook's final tracked line", () => {
  const bets = [
    {
      ticket_type: "single",
      fight_id: 1,
      bet_side: "fighter_a",
      bet_sportsbook: "DK",
      bet_price: -120,
      fighter_a: { fighter_id: 11 },
    },
    {
      ticket_type: "parlay",
      bet_sportsbook: "FD",
      legs: [
        {
          fight_id: 2,
          bet_side: "fighter_b",
          leg_price: 150,
          fighter_b: { fighter_id: 22 },
        },
      ],
    },
  ];
  const oddsByFight = {
    1: {
      11: [{ sportsbook_key: "draftkings", final_tracked_odds: -140 }],
    },
    2: {
      22: [{ sportsbook: "FanDuel", final_tracked_odds: 130 }],
    },
  };

  const summary = buildTrackedCloseDiagnostics(bets, oddsByFight);

  assert.equal(summary.comparison_count, 2);
  assert.equal(summary.beat_tracked_close_count, 2);
  assert.equal(summary.worse_than_tracked_close_count, 0);
  assert.equal(summary.beat_rate_percent, 100);
  assert.match(summary.terminology, /not a guaranteed market closing line/);
});

test("ignores unmatched books and missing final tracked prices", () => {
  const summary = buildTrackedCloseDiagnostics(
    [{
      fight_id: 1,
      bet_side: "fighter_a",
      bet_sportsbook: "BO",
      bet_price: -110,
      fighter_a: { fighter_id: 11 },
    }],
    { 1: { 11: [{ sportsbook: "DraftKings", final_tracked_odds: -125 }] } }
  );

  assert.equal(summary.comparison_count, 0);
  assert.equal(summary.beat_rate_percent, null);
  assert.match(summary.sample_guidance, /Small sample/);
});

test("summarizes saved completed leans without counting pass or unfinished rows", () => {
  const summary = summarizeLeanAccuracy([
    { user_lean: "fighter_a", fighter_a_id: 1, winner_id: 1 },
    { user_lean: "fighter_b", fighter_b_id: 2, winner_id: 1 },
    { user_lean: "pass", fighter_a_id: 3, winner_id: 3 },
    { user_lean: "fighter_a", fighter_a_id: 4, winner_id: null },
  ]);

  assert.equal(summary.completed_lean_count, 2);
  assert.equal(summary.wins, 1);
  assert.equal(summary.losses, 1);
  assert.equal(summary.accuracy_percent, 50);
});
