import assert from "node:assert/strict";
import test from "node:test";

import {
  historyCoverageLabel,
  historyEmptyMessage,
  historyRunLabel,
} from "./historyCoverage.js";

test("history coverage labels distinguish debut and unavailable regional history", () => {
  assert.equal(
    historyCoverageLabel({ coverage_status: "confirmed_debut" }),
    "Professional debut indicated"
  );
  assert.equal(
    historyCoverageLabel({ coverage_status: "regional_history_unavailable" }),
    "Prior record found; bout details unavailable"
  );
});

test("coverage note explains an empty history", () => {
  assert.equal(
    historyEmptyMessage({ coverage_note: "Record 4-1 indicates prior experience." }),
    "Record 4-1 indicates prior experience."
  );
});

test("weekly maintenance status has a compact label", () => {
  assert.equal(historyRunLabel({ status: "success" }), "Checked");
  assert.equal(historyRunLabel({ status: "partial" }), "Review needed");
});
