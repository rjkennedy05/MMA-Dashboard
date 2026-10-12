import test from "node:test";
import assert from "node:assert/strict";

import {
  americanOddsToImpliedProbability,
  americanOddsToDecimal,
  buildMoneylineHistory,
  calculateMoneylineMovement,
  combineAmericanOdds,
  decimalOddsToAmerican,
  formatAmericanOdds,
  getBestMoneyline,
} from "./odds.js";

test("converts American odds to raw implied probability", () => {
  assert.equal(americanOddsToImpliedProbability(-150), 0.6);
  assert.equal(americanOddsToImpliedProbability(200), 1 / 3);
  assert.equal(americanOddsToImpliedProbability(0), null);
});

test("selects the bettor-friendly best current moneyline", () => {
  const best = getBestMoneyline([
    { sportsbook: "A", american_odds: -145 },
    { sportsbook: "B", american_odds: -130 },
    { sportsbook: "C", american_odds: -155 },
  ]);

  assert.equal(best.sportsbook, "B");
});

test("builds same-book first, current, and final pre-fight snapshots", () => {
  const rows = [
    {
      odds_id: 1,
      fight_id: 9,
      fighter_id: 11,
      sportsbook: "DraftKings",
      sportsbook_key: "draftkings",
      american_odds: -120,
      recorded_at: "2026-08-10T12:00:00Z",
      market_commence_time: "2026-08-11T01:00:00Z",
    },
    {
      odds_id: 2,
      fight_id: 9,
      fighter_id: 11,
      sportsbook: "DraftKings Sportsbook",
      sportsbook_key: "draftkings",
      american_odds: -135,
      recorded_at: "2026-08-11T00:55:00Z",
      market_commence_time: "2026-08-11T01:00:00Z",
    },
    {
      odds_id: 3,
      fight_id: 9,
      fighter_id: 11,
      sportsbook: "DraftKings Sportsbook",
      sportsbook_key: "draftkings",
      american_odds: -145,
      recorded_at: "2026-08-11T01:05:00Z",
      market_commence_time: "2026-08-11T01:00:00Z",
    },
  ];

  const line = buildMoneylineHistory(rows)[9][11][0];

  assert.equal(line.first_tracked_odds, -120);
  assert.equal(line.american_odds, -145);
  assert.equal(line.final_tracked_odds, -135);
  assert.equal(line.snapshot_count, 3);
  assert.equal(line.sportsbook, "DraftKings Sportsbook");
});

test("movement uses probability points and honest formatting", () => {
  const movement = calculateMoneylineMovement(-120, -150);

  assert.equal(movement.direction, "shortened");
  assert.ok(movement.probabilityPointChange > 5);
  assert.equal(formatAmericanOdds(125), "+125");
  assert.equal(formatAmericanOdds(-125), "-125");
});

test("combines valid American parlay legs", () => {
  assert.equal(americanOddsToDecimal(-200), 1.5);
  assert.equal(decimalOddsToAmerican(2.25), 125);
  assert.equal(combineAmericanOdds([-200, -200]), 125);
  assert.equal(combineAmericanOdds([-200]), null);
});

test('representative snapshots retain the real history count across providers',()=>{
  const base={fight_id:1,fighter_id:11,sportsbook:'DraftKings',sportsbook_key:'draftkings'};
  const history=buildMoneylineHistory([
    {...base,recorded_at:'2026-10-10T10:00:00Z',american_odds:100,snapshot_group:'draftkings:1',snapshot_count:12},
    {...base,recorded_at:'2026-10-11T10:00:00Z',american_odds:110,snapshot_group:'draftkings:1',snapshot_count:12},
    {...base,recorded_at:'2026-10-12T10:00:00Z',american_odds:120,snapshot_group:'draftkings:2',snapshot_count:5},
  ]);
  assert.equal(history[1][11][0].snapshot_count,17);
});
