import assert from "node:assert/strict";
import test from "node:test";

import {
  calculateConsensus,
  createEmptySourcePicks,
  normalizeSourcePicks,
  STORED_CONSENSUS_SOURCES,
  VISIBLE_CONSENSUS_SOURCES,
} from "./consensus.js";

test("keeps five stored source slots while presenting three", () => {
  assert.equal(createEmptySourcePicks().length, STORED_CONSENSUS_SOURCES);
  assert.equal(VISIBLE_CONSENSUS_SOURCES, 3);
});

test("preserves hidden historical sources without counting them in consensus", () => {
  const normalized = normalizeSourcePicks([
    { label: "A", pick: "fighter_a" },
    { label: "B", pick: "fighter_a" },
    { label: "C", pick: "pass" },
    { label: "Old fourth source", pick: "fighter_b" },
    { label: "Old fifth source", pick: "fighter_b" },
  ]);

  assert.equal(normalized[3].label, "Old fourth source");
  assert.deepEqual(calculateConsensus(normalized), {
    counts: { fighter_a: 2, fighter_b: 0, pass: 1 },
    leader: "fighter_a",
    percentage: 67,
    total: 3,
  });
});
