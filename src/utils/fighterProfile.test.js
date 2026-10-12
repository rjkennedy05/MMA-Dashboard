import assert from "node:assert/strict";
import test from "node:test";

import {
  fighterAge,
  formatHeight,
  formatReach,
  profileCoverage,
} from "./fighterProfile.js";

test("formats physical measurements without inventing missing values", () => {
  assert.equal(formatHeight(77), "6' 5\"");
  assert.equal(formatReach(80), "80\"");
  assert.equal(formatHeight(null), "—");
  assert.equal(formatReach(undefined), "—");
});

test("prefers provider age and otherwise derives age from date of birth", () => {
  assert.equal(fighterAge({ age_snapshot: 31 }), 31);
  assert.equal(
    fighterAge(
      { date_of_birth: "1996-08-11" },
      new Date("2026-08-10T12:00:00Z")
    ),
    29
  );
});

test("reports profile coverage from real populated fields", () => {
  assert.deepEqual(
    profileCoverage({
      record_summary: "12-2-0",
      age_snapshot: 28,
      height_inches: 72,
    }),
    { available: 3, total: 6 }
  );
});
