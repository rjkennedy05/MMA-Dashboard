import assert from "node:assert/strict";
import test from "node:test";

import {
  extractAssistantMatchupAnalysis,
  finishSummary,
  inspectAssistantMatchupFacts,
  parseAssistantMatchupFacts,
  parseRecordWins,
} from "./assistantMatchupFacts.js";

const fights = [
  {
    fight_id: 10,
    fighter_a: { full_name: "Islam Makhachev" },
    fighter_b: { full_name: "Ian Machado Garry" },
  },
  {
    fight_id: 11,
    fighter_a: { full_name: "José Aldo" },
    fighter_b: { full_name: "Fighter Beta" },
  },
];

test("parses dashboard facts into the matching fight", () => {
  const analysis = `## Islam Makhachev vs Ian Machado Garry
**Dashboard facts:** A style=Pressure grappler; B style=Range striker; A record=27-1-0; B record=16-0-0; A KO/TKO wins=5; A submission wins=11; B KO/TKO wins=7; B submission wins=1
**Independent matchup read:** Test.

## Jose Aldo vs Fighter Beta
**Dashboard facts:** A style=Counter striker; B style=Unknown; A record=32-9-0; B record=unknown; A KO/TKO wins=17; A submission wins=1; B KO/TKO wins=unknown; B submission wins=N/A`;

  assert.deepEqual(parseAssistantMatchupFacts(analysis, fights), [
    {
      fight_id: 10,
      fighter_a_style: "Pressure grappler",
      fighter_b_style: "Range striker",
      fighter_a_record_summary: "27-1-0",
      fighter_b_record_summary: "16-0-0",
      fighter_a_ko_wins: 5,
      fighter_a_submission_wins: 11,
      fighter_b_ko_wins: 7,
      fighter_b_submission_wins: 1,
    },
    {
      fight_id: 11,
      fighter_a_style: "Counter striker",
      fighter_b_style: "",
      fighter_a_record_summary: "32-9-0",
      fighter_b_record_summary: "",
      fighter_a_ko_wins: 17,
      fighter_a_submission_wins: 1,
      fighter_b_ko_wins: null,
      fighter_b_submission_wins: null,
    },
  ]);
});

test("ignores sections without a complete dashboard facts line", () => {
  assert.deepEqual(
    parseAssistantMatchupFacts(
      "## Islam Makhachev vs Ian Machado Garry\n**Independent matchup read:** Test.",
      fights
    ),
    []
  );
});

test("accepts wrapped dashboard facts with labels, colons, and markdown bullets", () => {
  const analysis = `### **Islam Makhachev vs. Ian Machado Garry**
**Dashboard facts:**
- **A style:** Pressure grappler
- **B style:** Range striker
- **A record:** 27–1 (record citation)
- **B record:** 16-0-0
- **A KO/TKO wins:** 5
- **A submission wins:** 11
- **B KO/TKO wins:** 7
- **B submission wins:** 1
**Independent matchup read:** Test.`;

  assert.deepEqual(parseAssistantMatchupFacts(analysis, fights), [
    {
      fight_id: 10,
      fighter_a_style: "Pressure grappler",
      fighter_b_style: "Range striker",
      fighter_a_record_summary: "27-1-0",
      fighter_b_record_summary: "16-0-0",
      fighter_a_ko_wins: 5,
      fighter_a_submission_wins: 11,
      fighter_b_ko_wins: 7,
      fighter_b_submission_wins: 1,
    },
  ]);
});

test("persists only the matchup narrative when facts and the read use wrapped lines", () => {
  const analysis = `### **Islam Makhachev vs. Ian Machado Garry**
**Dashboard facts:**
- **A style:** Pressure grappler
- **B style:** Range striker
- **A record:** 27-1-0
- **B record:** 16-0-0
- **A KO/TKO wins:** 5
- **A submission wins:** 11
- **B KO/TKO wins:** 7
- **B submission wins:** 1
**Independent matchup read:** This is the durable matchup narrative.`;

  const inspection = inspectAssistantMatchupFacts(analysis, fights.slice(0, 1));
  assert.equal(inspection.updates.length, 1);
  assert.match(inspection.updates[0].assistant_matchup_analysis, /durable matchup narrative/);
  assert.doesNotMatch(inspection.updates[0].assistant_matchup_analysis, /A style/);
});

test("matches reversed fighter headings and swaps A/B facts into dashboard order", () => {
  const analysis = `## Ian Garry v Islam Makhachev
Dashboard facts: A style=Range striker; B style=Pressure grappler; A record=16-0; B record=27-1; A KO wins=7; A sub wins=1; B KO wins=5; B sub wins=11`;

  assert.deepEqual(parseAssistantMatchupFacts(analysis, fights), [
    {
      fight_id: 10,
      fighter_a_style: "Pressure grappler",
      fighter_b_style: "Range striker",
      fighter_a_record_summary: "27-1-0",
      fighter_b_record_summary: "16-0-0",
      fighter_a_ko_wins: 5,
      fighter_a_submission_wins: 11,
      fighter_b_ko_wins: 7,
      fighter_b_submission_wins: 1,
    },
  ]);
});

test("persists a recognized matchup narrative even when its facts block is missing", () => {
  const inspection = inspectAssistantMatchupFacts(
    "## Islam Makhachev vs Ian Machado Garry\n**Independent matchup read:** Test.",
    fights
  );

  assert.equal(inspection.updates.length, 1);
  assert.equal(inspection.updates[0].fight_id, 10);
  assert.match(inspection.updates[0].assistant_matchup_analysis, /Independent matchup read/);
  assert.equal(inspection.sectionCount, 1);
  assert.equal(inspection.factBlockCount, 0);
  assert.deepEqual(inspection.unmatchedFights.map((fight) => fight.fight_id), [11]);
});

test("accepts numbered plain-text matchup headings", () => {
  const analysis = `1. Islam Makhachev vs Ian Machado Garry
Dashboard facts: A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1`;

  const inspection = inspectAssistantMatchupFacts(analysis, fights.slice(0, 1));
  assert.equal(inspection.updates.length, 1);
  assert.equal(inspection.updates[0].fight_id, 10);
});

test("matches dashboard facts by stable fight key without relying on headings", () => {
  const analysis = `Main event breakdown
**Dashboard facts [key=10]:** A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1`;

  const inspection = inspectAssistantMatchupFacts(analysis, fights.slice(0, 1));
  assert.equal(inspection.updates.length, 1);
  assert.equal(inspection.matchStrategy, "keys");
});

test("stops a facts block before the readable matchup sections", () => {
  const analysis = `## Fight 1: Islam Makhachev vs Ian Machado Garry
### Snapshot
| | Islam Makhachev | Ian Machado Garry |
|---|---|---|
| Style | Pressure grappler | Range striker |
**Dashboard facts [key=10]:** A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1

### Matchup read
This paragraph must not become part of the final imported value.`;

  const inspection = inspectAssistantMatchupFacts(analysis, fights.slice(0, 1));
  assert.equal(inspection.updates.length, 1);
  assert.equal(inspection.updates[0].fighter_b_submission_wins, 1);
});

test("uses card order when every fight has a facts block but headings were reformatted", () => {
  const analysis = `Main event
Dashboard facts: A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1

Co-main event
Dashboard facts: A style=Counter striker; B style=Unknown; A record=32-9; B record=unknown; A KO wins=17; A sub wins=1; B KO wins=unknown; B sub wins=unknown`;

  const inspection = inspectAssistantMatchupFacts(analysis, fights);
  assert.equal(inspection.updates.length, 2);
  assert.equal(inspection.matchStrategy, "card order");
  assert.deepEqual(inspection.updates.map((update) => update.fight_id), [10, 11]);
});

test("extracts the selected fight analysis by stable fight key", () => {
  const analysis = `## Fight 1: Islam Makhachev vs Ian Machado Garry
### Snapshot
| | Islam Makhachev | Ian Machado Garry |
|---|---|---|
**Dashboard facts [key=10]:** A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1

### Local connection
- **Islam Makhachev:** Trains far from the venue.
- **Ian Machado Garry:** No verified local connection.
- **Relevance:** Minimal.

### Matchup read
Fight one narrative.

### Price check
- **Projected winner:** Islam Makhachev

## Fight 2: José Aldo vs Fighter Beta
**Dashboard facts [key=11]:** A style=Counter striker; B style=Pressure fighter; A record=32-9; B record=12-2; A KO wins=17; A sub wins=1; B KO wins=6; B sub wins=2

### Matchup read
Fight two narrative.`;

  const excerpt = extractAssistantMatchupAnalysis(analysis, fights[0]);

  assert.match(excerpt, /^### Local connection/);
  assert.match(excerpt, /Fight one narrative/);
  assert.match(excerpt, /Projected winner/);
  assert.doesNotMatch(excerpt, /Dashboard facts/);
  assert.doesNotMatch(excerpt, /Fight two narrative/);
});

test("extracts a legacy saved analysis by matchup heading", () => {
  const analysis = `## Islam Makhachev vs Ian Machado Garry
Dashboard facts: A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1

### Matchup read
Legacy narrative remains available.`;

  assert.match(
    extractAssistantMatchupAnalysis(analysis, fights[0]),
    /Legacy narrative remains available/
  );
});

test("imports structured facts and the full keyed matchup narrative without the card summary", () => {
  const analysis = `## Fight 1: Islam Makhachev vs Ian Machado Garry [key=10]

### Snapshot
| | Islam Makhachev | Ian Machado Garry |
|---|---|---|
| Style | Pressure grappler | Range striker |

### Matchup read
This is the complete first paragraph of the keyed matchup read.

This is the second paragraph and it must also import.

### Paths & risks
- **Islam Makhachev win path:** Control and top pressure.
- **Ian Machado Garry win path:** Long-range counters.

### Context
- **Local/camp:** No verified local connection.

### Verdict & price
- **Pick:** Islam Makhachev

## Card Summary
- This card-level text must not appear in the selected fight.

## Dashboard Import
**Dashboard facts [key=10]:** A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1
**Decision data [key=10]:** pick=fighter_a; win probability=67; fair moneyline=-203; buy at=-175; rank=A; reliability=strong; volatility=medium; betting assessment=Bet at -175 or better; win path=Control and top pressure; upset path=Long-range counters; confidence limiter=Open-space entries`;

  const [update] = parseAssistantMatchupFacts(analysis, fights.slice(0, 1));
  const excerpt = extractAssistantMatchupAnalysis(analysis, fights[0]);

  assert.equal(update.fight_id, 10);
  assert.equal(update.assistant_pick, "fighter_a");
  assert.match(excerpt, /^### Matchup read/);
  assert.match(excerpt, /second paragraph/);
  assert.match(excerpt, /### Verdict & price/);
  assert.doesNotMatch(excerpt, /Card Summary/);
  assert.doesNotMatch(excerpt, /Dashboard facts/);
  assert.doesNotMatch(excerpt, /Decision data/);
});

test("recovers matchup narrative from a reformatted heading when the key is preserved", () => {
  const analysis = `## Main Event Breakdown [key=10]
### Full matchup read
The promotion chat changed the title, but this complete analysis must still import.

### Verdict & price
- **Pick:** Islam Makhachev

## Dashboard Import
Dashboard facts [key=10]: A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1`;

  const excerpt = extractAssistantMatchupAnalysis(analysis, fights[0]);

  assert.match(excerpt, /^### Full matchup read/);
  assert.match(excerpt, /complete analysis must still import/);
  assert.doesNotMatch(excerpt, /Dashboard facts/);
});

test("summarizes finishes against total wins", () => {
  assert.equal(parseRecordWins("27-1-0"), 27);
  assert.equal(finishSummary({ koWins: 5, submissionWins: 11, recordSummary: "27-1-0" }), "16 of 27 wins (59%)");
  assert.equal(finishSummary({ koWins: null, submissionWins: 2, recordSummary: "10-2-0" }), "—");
});

test("imports structured decision data for ranking and price discipline", () => {
  const analysis = `## Islam Makhachev vs Ian Machado Garry
**Dashboard facts [key=10]:** A style=Pressure grappler; B style=Range striker; A record=27-1; B record=16-0; A KO wins=5; A sub wins=11; B KO wins=7; B sub wins=1
**Decision data [key=10]:** pick=fighter_a; win probability=67; fair moneyline=-203; buy at=-175; rank=A; reliability=strong; volatility=medium; betting assessment=Bet at -175 or better; win path=Control and top pressure; upset path=Long-range counter striking; confidence limiter=Open-space takedown entries`;

  const [update] = parseAssistantMatchupFacts(analysis, fights.slice(0, 1));
  assert.equal(update.assistant_pick, "fighter_a");
  assert.equal(update.assistant_win_probability, 67);
  assert.equal(update.assistant_fair_moneyline, -203);
  assert.equal(update.assistant_target_price, -175);
  assert.equal(update.assistant_rank, "A");
  assert.equal(update.assistant_reliability, "strong");
  assert.equal(update.assistant_volatility, "medium");
  assert.match(update.assistant_betting_assessment, /Bet at -175/);
  assert.match(update.assistant_win_path, /top pressure/);
  assert.match(update.assistant_upset_path, /counter striking/);
});
