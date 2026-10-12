import assert from "node:assert/strict";
import test from "node:test";

import { buildCardAnalysisPrompt } from "./cardAnalysisPrompt.js";

const fights = [
  {
    fight_id: 10,
    fight_order: 1,
    scheduled_rounds: 3,
    is_title_fight: false,
    weight_classes: { name: "Lightweight" },
    events: {
      event_name: "Test Card",
      event_date: "2026-08-11",
      event_start_time: "2026-08-12T00:00:00Z",
      watch_platform: "Paramount+",
      city: "Las Vegas",
      state_region: "Nevada",
      country: "USA",
      promotions: { name: "DWCS" },
    },
    fighter_a: {
      fighter_id: 101,
      full_name: "Fighter Alpha",
      record_summary: "9-1-0",
      age_snapshot: 27,
      height_inches: 72,
      reach_inches: 75,
      profile_source: { name: "ESPN MMA" },
    },
    fighter_b: { fighter_id: 102, full_name: "Fighter Beta" },
  },
  {
    fight_id: 11,
    fight_order: 2,
    scheduled_rounds: 3,
    is_title_fight: false,
    weight_classes: { name: "Welterweight" },
    events: { event_name: "Test Card", promotions: { name: "DWCS" } },
    fighter_a: { fighter_id: 103, full_name: "Fighter Gamma" },
    fighter_b: { fighter_id: 104, full_name: "Fighter Delta" },
  },
];

test("buildCardAnalysisPrompt requests compact matchup facts for every fight", () => {
  const prompt = buildCardAnalysisPrompt({
    fights,
    oddsByFight: {
      10: {
        101: [{ sportsbook: "Book A", opening_odds: -120, american_odds: -135 }],
      },
    },
    researchByFight: {
      10: {
        fighter_a_style: "Range striker",
        fighter_a_ko_wins: 4,
        fighter_a_submission_wins: 1,
        user_lean: "fighter_a",
        source_picks: [{ label: "Source One", pick: "fighter_b" }],
      },
    },
    performanceDiagnostics: {
      tracked_close_movement: {
        comparison_count: 8,
        beat_rate_percent: 62.5,
      },
      saved_lean_accuracy: {
        completed_lean_count: 12,
        accuracy_percent: 58.3,
      },
    },
    historiesByFighter: {
      101: [{
        date: "2026-05-01",
        promotion: "LFA",
        opponent: { full_name: "Proven Opponent" },
        opponentRecord: "12-3-0",
        opponentRecordQuality: "winning",
        outcome: "W",
        method: "KO/TKO",
        round: 2,
        status: "completed",
        titleFight: false,
      }],
    },
  });

  assert.match(prompt, /MMA DASHBOARD CARD RESPONSE CONTRACT v4/);
  assert.match(prompt, /Start directly with Fight 1/);
  assert.match(prompt, /persist and render it on the correct matchup/);
  assert.match(prompt, /overrides any older response format/);
  assert.match(prompt, /same structure for every promotion/);
  assert.match(prompt, /## Fight \[card order\].*\[key=exact dashboard_import_key\]/);
  assert.match(prompt, /### Snapshot/);
  assert.match(prompt, /KO\/TKO wins/);
  assert.match(prompt, /Submission wins/);
  assert.match(prompt, /### Matchup read/);
  assert.match(prompt, /complete 140–220 word handicap/);
  assert.match(prompt, /Proven Opponent/);
  assert.match(prompt, /opponent_record_quality/);
  assert.match(prompt, /cancellations\/rebookings/);
  assert.match(prompt, /### Context/);
  assert.match(prompt, /hometown, residence, and current training-camp/);
  assert.match(prompt, /No verified local connection/);
  assert.match(prompt, /### Paths & risks/);
  assert.match(prompt, /fight\/fighter volatility—not market movement/);
  assert.match(prompt, /Confidence limiter/);
  assert.match(prompt, /### Verdict & price/);
  assert.match(prompt, /Win probability/);
  assert.match(prompt, /Fair moneyline/);
  assert.match(prompt, /## Card Summary/);
  assert.match(prompt, /## Dashboard Import/);
  assert.match(prompt, /Decision data \[key=/);
  assert.match(prompt, /buy at=\[American odds\]/);
  assert.match(prompt, /rank=\[A, B, C, or D\]/);
  assert.match(prompt, /Fighter Alpha vs Fighter Beta/);
  assert.match(prompt, /Fighter Gamma vs Fighter Delta/);
  assert.match(prompt, /Range striker/);
  assert.match(prompt, /fighter_a_ko_tko_wins/);
  assert.match(prompt, /Dashboard facts/);
  assert.match(prompt, /dashboard_import_key/);
  assert.match(prompt, /Dashboard facts \[key=/);
  assert.match(prompt, /A KO\/TKO wins=\[integer or unknown\]/);
  assert.match(prompt, /Source One/);
  assert.match(prompt, /-135/);
  assert.match(prompt, /current_record_snapshot/);
  assert.match(prompt, /9-1-0/);
  assert.match(prompt, /ESPN MMA/);
  assert.doesNotMatch(prompt, /RIZIN: exact ruleset/);
  assert.match(prompt, /process_diagnostics/);
  assert.match(prompt, /beat_rate_percent/);
  assert.match(prompt, /Do not add a process-diagnostics section/);
  assert.match(prompt, /every CARD DATA fight appears once/);
  assert.match(prompt, /every fight has a complete Matchup read/);
  assert.doesNotMatch(prompt, /fighter_a_ratings/);
});

test("buildCardAnalysisPrompt rejects an empty card", () => {
  assert.throws(
    () => buildCardAnalysisPrompt({ fights: [] }),
    /does not have any fights/
  );
});
