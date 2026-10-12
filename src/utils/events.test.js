import assert from "node:assert/strict";
import test from "node:test";

import {
  eventBrowserWindow,
  eventMatchesSearch,
  formatEventStatus,
  isDevelopmentEvent,
  splitEventWindow,
} from "./events.js";

test("hides only the known UFC development rows", () => {
  assert.equal(
    isDevelopmentEvent({ event_name: "UFC Test Event" }),
    true
  );
  assert.equal(
    isDevelopmentEvent({ event_name: " UFC Import Test " }),
    true
  );
  assert.equal(isDevelopmentEvent({ event_name: "Test Event" }), true);
  assert.equal(
    isDevelopmentEvent({ event_name: "UFC Import Test Event 2" }),
    true
  );
  assert.equal(
    isDevelopmentEvent({
      event_name: "UFC Fight Night: Medić vs. Rodriguez",
    }),
    false
  );
});

test("keeps all upcoming cards and only the last 30 days of results", () => {
  const events = [
    { event_id: 1, event_date: "2026-09-10", event_status: "upcoming" },
    { event_id: 2, event_date: "2026-08-10", event_status: "live" },
    { event_id: 3, event_date: "2026-08-10", event_status: "completed" },
    { event_id: 4, event_date: "2026-07-11", event_status: "completed" },
    { event_id: 5, event_date: "2026-07-10", event_status: "completed" },
  ];

  const window = splitEventWindow(events, "2026-08-10");

  assert.deepEqual(
    window.upcoming.map((event) => event.event_id),
    [1, 2]
  );
  assert.deepEqual(
    window.recent.map((event) => event.event_id),
    [3, 4]
  );
});

test("splitEventWindow supports a seven-day two-sided window", () => {
  const events = [
    { event_id: 1, event_date: "2026-08-17", event_status: "upcoming" },
    { event_id: 2, event_date: "2026-08-18", event_status: "upcoming" },
    { event_id: 3, event_date: "2026-08-10", event_status: "live" },
    { event_id: 4, event_date: "2026-08-10", event_status: "completed" },
    { event_id: 5, event_date: "2026-08-03", event_status: "completed" },
    { event_id: 6, event_date: "2026-08-02", event_status: "completed" },
  ];

  const window = splitEventWindow(events, "2026-08-10", 7, 7);

  assert.deepEqual(
    window.upcoming.map((event) => event.event_id),
    [1, 3]
  );
  assert.deepEqual(
    window.recent.map((event) => event.event_id),
    [4, 5]
  );
});

test("All Cards shows only upcoming cards in the next seven days", () => {
  const events = [
    { event_id: 1, event_date: "2026-08-17", event_status: "upcoming" },
    { event_id: 2, event_date: "2026-08-18", event_status: "upcoming" },
    { event_id: 3, event_date: "2026-08-10", event_status: "live" },
    { event_id: 4, event_date: "2026-08-09", event_status: "completed" },
  ];

  const window = eventBrowserWindow(events, "2026-08-10", true);

  assert.deepEqual(
    window.upcoming.map((event) => event.event_id),
    [1, 3]
  );
  assert.deepEqual(window.recent, []);
});

test("promotion views retain all upcoming and thirty days of recent cards", () => {
  const events = [
    { event_id: 1, event_date: "2027-01-01", event_status: "upcoming" },
    { event_id: 2, event_date: "2026-07-12", event_status: "completed" },
    { event_id: 3, event_date: "2026-07-10", event_status: "completed" },
  ];

  const window = eventBrowserWindow(events, "2026-08-10", false);

  assert.deepEqual(
    window.upcoming.map((event) => event.event_id),
    [1]
  );
  assert.deepEqual(
    window.recent.map((event) => event.event_id),
    [2]
  );
});

test("does not move a future card into recent because of a stale status", () => {
  const window = splitEventWindow(
    [
      {
        event_id: 1,
        event_date: "2026-08-15",
        event_status: "completed",
      },
    ],
    "2026-08-10"
  );

  assert.equal(window.upcoming.length, 1);
  assert.equal(window.recent.length, 0);
});

test("normalizes event statuses for display", () => {
  assert.equal(formatEventStatus({ event_status: "in_progress" }), "Live");
  assert.equal(formatEventStatus({ event_status: "final" }), "Completed");
  assert.equal(formatEventStatus({ event_status: "postponed" }), "Cancelled");
  assert.equal(formatEventStatus({ event_status: "upcoming" }), "Scheduled");
});

test("searches event metadata and fighter names", () => {
  const event = {
    event_name: "UFC 330",
    city: "New York",
    watch_platform: "ESPN+",
    promotions: { name: "UFC" },
    fights: [
      {
        fighter_a: { full_name: "Islam Makhachev" },
        fighter_b: { full_name: "Ian Machado Garry" },
      },
    ],
  };

  assert.equal(eventMatchesSearch(event, "Makhachev"), true);
  assert.equal(eventMatchesSearch(event, "new york"), true);
  assert.equal(eventMatchesSearch(event, "PFL"), false);
});
