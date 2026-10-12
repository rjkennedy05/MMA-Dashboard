import assert from "node:assert/strict";
import test from "node:test";

import { buildResearchBoardRows, rankLabel } from "./researchRanking.js";

test("research rows keep all tiers ordered for the board filters", () => {
  const fight = {
    fight_id: 1,
    fighter_a: { fighter_id: 10, full_name: "A" },
    fighter_b: { fighter_id: 11, full_name: "B" },
    events: { event_date: "2026-09-20" },
  };
  const rows = buildResearchBoardRows([
    { fight: { ...fight, fight_id: 2 }, assistant_rank: "C", assistant_pick: "fighter_a" },
    { fight, assistant_rank: "A", assistant_pick: "fighter_a" },
  ]);
  assert.equal(rows[0].assistant_rank, "A");
  assert.equal(rows[1].assistant_rank, "C");
  assert.equal(rankLabel("B"), "B");
});
