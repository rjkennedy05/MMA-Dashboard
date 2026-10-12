import assert from "node:assert/strict";
import test from "node:test";

import {
  fighterDecisionClass,
  getResearchDecision,
  researchStatusForDecision,
} from "./researchDecision.js";

test("uses the saved lean as the unified research decision", () => {
  assert.equal(getResearchDecision({ user_lean: "fighter_a" }), "fighter_a");
  assert.equal(getResearchDecision({ user_lean: "fighter_b" }), "fighter_b");
  assert.equal(getResearchDecision({ user_lean: "pass" }), "pass");
  assert.equal(getResearchDecision({ user_lean: "wait" }), "");
  assert.equal(getResearchDecision({ research_status: "pass" }), "pass");
});

test("maps the four UI decisions to compatible saved research statuses", () => {
  assert.equal(researchStatusForDecision(""), "not_started");
  assert.equal(researchStatusForDecision("fighter_a"), "initial_lean");
  assert.equal(researchStatusForDecision("fighter_b"), "initial_lean");
  assert.equal(researchStatusForDecision("pass"), "pass");
});

test("highlights only the selected fighter and both fighters for a pass", () => {
  assert.equal(fighterDecisionClass("fighter_a", "fighter_a"), "fighter-lean-highlight");
  assert.equal(fighterDecisionClass("fighter_a", "fighter_b"), "");
  assert.equal(fighterDecisionClass("pass", "fighter_a"), "fighter-pass-highlight");
  assert.equal(fighterDecisionClass("pass", "fighter_b"), "fighter-pass-highlight");
});
