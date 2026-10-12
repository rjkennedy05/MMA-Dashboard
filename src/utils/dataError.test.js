import assert from "node:assert/strict";
import test from "node:test";

import { userFacingDataError } from "./dataError.js";

test("turns JWT future errors into a clock-repair message", () => {
  const message = userFacingDataError(
    new Error("JWT issued at future 1750000000"),
    "Could not load data."
  );
  assert.match(message, /computer clock is out of sync/i);
  assert.match(message, /saved data has not been deleted/i);
});

test("preserves useful provider errors and uses a fallback when empty", () => {
  assert.equal(
    userFacingDataError(new Error("Database unavailable"), "Fallback"),
    "Database unavailable"
  );
  assert.equal(userFacingDataError(null, "Fallback"), "Fallback");
});
