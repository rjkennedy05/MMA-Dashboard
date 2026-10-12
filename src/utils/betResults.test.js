import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateBetProfit,
  groupBetsByPromotionAndEvent,
  didBetTicketChange,
  getOfficialSettlementSuggestion,
  getParlaySettlementSuggestion,
  suggestOfficialSettlement,
  summarizeBets,
  summarizeBetsByPromotion,
} from "./betResults.js";

test("suggestOfficialSettlement compares the saved side with the official winner", () => {
  const baseBet = {
    settlement_status: "pending",
    fight_status: "completed",
    winner_id: 11,
    fighter_a: { fighter_id: 11 },
    fighter_b: { fighter_id: 22 },
  };

  assert.equal(
    suggestOfficialSettlement({ ...baseBet, bet_side: "fighter_a" }),
    "win"
  );
  assert.equal(
    suggestOfficialSettlement({ ...baseBet, bet_side: "fighter_b" }),
    "loss"
  );
});

test("suggestOfficialSettlement leaves the book-rule decision reviewable", () => {
  assert.equal(
    suggestOfficialSettlement({
      settlement_status: "pending",
      fight_status: "no_contest",
    }),
    "void"
  );
  assert.equal(
    suggestOfficialSettlement({
      settlement_status: "win",
      fight_status: "completed",
      winner_id: 1,
    }),
    null
  );
});

test("official settlement suggestions explain certainty and book-rule reviews", () => {
  const official = getOfficialSettlementSuggestion({
    settlement_status: "pending",
    fight_status: "completed",
    winner_id: 11,
    bet_side: "fighter_a",
    selection_name: "Winner Name",
    fighter_a: { fighter_id: 11 },
  });
  assert.deepEqual(official, {
    status: "win",
    confidence: "official",
    reason: "Winner Name is the official winner.",
  });

  const bookReview = getOfficialSettlementSuggestion({
    settlement_status: "pending",
    fight_status: "cancelled",
  });
  assert.equal(bookReview.status, "void");
  assert.equal(bookReview.confidence, "review");
  assert.match(bookReview.reason, /sportsbook/i);
});

test("parlays grade from official leg outcomes without guessing book-rule reductions", () => {
  const base = {
    ticket_type: "parlay",
    settlement_status: "pending",
    legs: [
      {
        fight_status: "completed",
        winner_id: 1,
        bet_side: "fighter_a",
        fighter_a: { fighter_id: 1 },
        selection_name: "First Winner",
      },
      {
        fight_status: "completed",
        winner_id: 2,
        bet_side: "fighter_b",
        fighter_b: { fighter_id: 2 },
        selection_name: "Second Winner",
      },
    ],
  };

  assert.equal(getParlaySettlementSuggestion(base).status, "win");
  assert.equal(
    getParlaySettlementSuggestion({
      ...base,
      legs: [
        base.legs[0],
        { ...base.legs[1], winner_id: 3 },
      ],
    }).status,
    "loss"
  );
  assert.equal(
    getParlaySettlementSuggestion({
      ...base,
      legs: [base.legs[0], { ...base.legs[1], fight_status: "no_contest" }],
    }),
    null
  );
});

test("detects material ticket edits without treating numeric formatting as a change", () => {
  const saved = {
    bet_side: "fighter_a",
    bet_sportsbook: "DraftKings",
    bet_price: -135,
    stake_units: 1,
  };

  assert.equal(didBetTicketChange(saved, { ...saved, stake_units: "1.0" }), false);
  assert.equal(didBetTicketChange(saved, { ...saved, bet_price: -130 }), true);
  assert.equal(didBetTicketChange(saved, { ...saved, bet_side: "fighter_b" }), true);
});

test("calculates wins at negative and positive American odds", () => {
  assert.equal(
    calculateBetProfit({
      bet_price: -200,
      stake_units: 1,
      settlement_status: "win",
    }),
    0.5
  );

  assert.equal(
    calculateBetProfit({
      bet_price: 150,
      stake_units: 2,
      settlement_status: "win",
    }),
    3
  );
});

test("losses subtract stake while pushes and pending bets return zero", () => {
  assert.equal(
    calculateBetProfit({
      bet_price: -135,
      stake_units: 1.25,
      settlement_status: "loss",
    }),
    -1.25
  );
  assert.equal(
    calculateBetProfit({
      bet_price: 200,
      stake_units: 1,
      settlement_status: "push",
    }),
    0
  );
});

test("summarizes record, risk, profit, ROI, and pending exposure", () => {
  const summary = summarizeBets([
    { bet_price: -200, stake_units: 1, settlement_status: "win" },
    { bet_price: 150, stake_units: 2, settlement_status: "win" },
    { bet_price: -110, stake_units: 1, settlement_status: "loss" },
    { bet_price: -120, stake_units: 0.5, settlement_status: "pending" },
    { bet_price: -105, stake_units: 1, settlement_status: "push" },
  ]);

  assert.equal(summary.tracked, 5);
  assert.equal(summary.wins, 2);
  assert.equal(summary.losses, 1);
  assert.equal(summary.pushes, 1);
  assert.equal(summary.pending, 1);
  assert.equal(summary.pendingRisk, 0.5);
  assert.equal(summary.gradedRisk, 4);
  assert.equal(summary.netProfit, 2.5);
  assert.equal(summary.roi, 62.5);
});

test("groups results by promotion", () => {
  const groups = summarizeBetsByPromotion([
    {
      promotion_name: "UFC",
      bet_price: -100,
      stake_units: 1,
      settlement_status: "win",
    },
    {
      promotion_name: "PFL",
      bet_price: 200,
      stake_units: 1,
      settlement_status: "loss",
    },
  ]);

  assert.deepEqual(
    groups.map(({ promotion, netProfit }) => [promotion, netProfit]),
    [["PFL", -1], ["UFC", 1]]
  );
});

test("builds a promotion and event tree for drill-down bet views", () => {
  const tree = groupBetsByPromotionAndEvent([
    {
      promotion_name: "UFC",
      event_id: 12,
      event_name: "UFC Test Two",
      event_date: "2026-08-15",
      bet_price: -110,
      stake_units: 1,
      settlement_status: "pending",
    },
    {
      promotion_name: "UFC",
      event_id: 11,
      event_name: "UFC Test One",
      event_date: "2026-08-08",
      bet_price: 120,
      stake_units: 1,
      settlement_status: "win",
    },
    {
      promotion_name: "ONE",
      event_id: 21,
      event_name: "ONE Friday Fights 166",
      event_date: "2026-08-14",
      bet_price: -150,
      stake_units: 1,
      settlement_status: "loss",
    },
  ]);

  assert.equal(tree.length, 2);
  assert.equal(tree[0].promotion, "UFC");
  assert.equal(tree[0].summary.tracked, 2);
  assert.deepEqual(
    tree[0].events.map((event) => event.eventId),
    [12, 11]
  );
  assert.equal(tree[1].events[0].eventName, "ONE Friday Fights 166");
});
