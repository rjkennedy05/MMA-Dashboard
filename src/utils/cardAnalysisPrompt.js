function formatOdds(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  return Number(value) > 0 ? `+${value}` : `${value}`;
}

function compactOdds(lines) {
  return (Array.isArray(lines) ? lines : []).slice(0, 8).map((line) => ({
    sportsbook: line.sportsbook ?? "Unknown book",
    first_tracked: formatOdds(line.first_tracked_odds ?? line.opening_odds),
    current: formatOdds(line.american_odds),
    final_tracked_pre_fight: formatOdds(line.final_tracked_odds),
    snapshots: line.snapshot_count ?? 1,
  }));
}

function compactSourcePicks(sourcePicks, fighterAName, fighterBName) {
  const pickLabels = {
    fighter_a: fighterAName,
    fighter_b: fighterBName,
    pass: "Pass",
  };

  return (Array.isArray(sourcePicks) ? sourcePicks : [])
    .filter((entry) => entry?.label?.trim() && entry?.pick)
    .slice(0, 5)
    .map((entry) => ({
      source: entry.label.trim(),
      pick: pickLabels[entry.pick] ?? entry.pick,
    }));
}

function compactHistory(history) {
  return (Array.isArray(history) ? history : []).slice(0, 12).map((entry) => ({
    date: entry.date,
    promotion: entry.promotion,
    opponent: entry.opponent?.full_name ?? null,
    opponent_current_record: entry.opponentRecord,
    opponent_record_quality: entry.opponentRecordQuality,
    result: entry.outcome,
    method: entry.method,
    round: entry.round,
    status: entry.status,
    title_fight: entry.titleFight,
  }));
}

function compactFighter(fighter, history = []) {
  return {
    name: fighter?.full_name ?? "Unknown fighter",
    nickname: fighter?.nickname ?? null,
    current_record_snapshot: fighter?.record_summary ?? null,
    age_snapshot: fighter?.age_snapshot ?? null,
    date_of_birth: fighter?.date_of_birth ?? null,
    height_inches: fighter?.height_inches ?? null,
    reach_inches: fighter?.reach_inches ?? null,
    stance: fighter?.stance ?? null,
    nationality: fighter?.nationality ?? null,
    profile_source: fighter?.profile_source?.name ?? null,
    profile_last_synced: fighter?.profile_updated_at ?? null,
    retained_dashboard_history: compactHistory(history),
  };
}

function getFightContext(fight, research, fightOdds, historiesByFighter) {
  const fighterAName = fight.fighter_a?.full_name ?? "Fighter A";
  const fighterBName = fight.fighter_b?.full_name ?? "Fighter B";
  const leanLabels = {
    fighter_a: fighterAName,
    fighter_b: fighterBName,
    wait: "Wait",
    pass: "Pass",
  };

  return {
    dashboard_import_key: String(fight.fight_id),
    card_order: fight.fight_order ?? null,
    matchup: `${fighterAName} vs ${fighterBName}`,
    weight_class: fight.weight_classes?.name ?? null,
    ruleset: fight.ruleset ?? null,
    official_bout_type: fight.bout_type ?? null,
    scheduled_rounds: fight.scheduled_rounds ?? 3,
    title_fight: Boolean(fight.is_title_fight),
    fighter_a: compactFighter(
      fight.fighter_a,
      historiesByFighter?.[fight.fighter_a?.fighter_id]
    ),
    fighter_b: compactFighter(
      fight.fighter_b,
      historiesByFighter?.[fight.fighter_b?.fighter_id]
    ),
    tracked_moneylines: {
      [fighterAName]: compactOdds(
        fightOdds?.[fight.fighter_a?.fighter_id]
      ),
      [fighterBName]: compactOdds(
        fightOdds?.[fight.fighter_b?.fighter_id]
      ),
    },
    user_research_unverified: {
      fighter_a_style: research?.fighter_a_style ?? "",
      fighter_b_style: research?.fighter_b_style ?? "",
      fighter_a_researched_record: research?.fighter_a_record_summary ?? "",
      fighter_b_researched_record: research?.fighter_b_record_summary ?? "",
      fighter_a_ko_tko_wins: research?.fighter_a_ko_wins ?? null,
      fighter_a_submission_wins:
        research?.fighter_a_submission_wins ?? null,
      fighter_b_ko_tko_wins: research?.fighter_b_ko_wins ?? null,
      fighter_b_submission_wins:
        research?.fighter_b_submission_wins ?? null,
      current_lean: leanLabels[research?.user_lean] ?? "No lean",
      target_moneyline: formatOdds(research?.target_price),
      outside_source_picks: compactSourcePicks(
        research?.source_picks,
        fighterAName,
        fighterBName
      ),
    },
  };
}

export function buildCardAnalysisPrompt({
  fights,
  oddsByFight = {},
  researchByFight = {},
  performanceDiagnostics = null,
  historiesByFighter = {},
}) {
  if (!Array.isArray(fights) || fights.length === 0) {
    throw new Error("This event does not have any fights to analyze.");
  }

  const firstFight = fights[0];
  const event = firstFight.events ?? {};
  const location = [event.city, event.state_region, event.country]
    .filter(Boolean)
    .join(", ");

  const context = {
    event: {
      promotion: event.promotions?.name ?? null,
      name: event.event_name ?? null,
      date: event.event_date ?? null,
      start_time: event.event_start_time ?? null,
      watch_platform: event.watch_platform ?? null,
      location: location || null,
    },
    fights: fights.map((fight) =>
      getFightContext(
        fight,
        researchByFight[fight.fight_id],
        oddsByFight[fight.fight_id],
        historiesByFighter
      )
    ),
    process_diagnostics: performanceDiagnostics,
  };

  return `You are my independent MMA betting analyst. Research and analyze the entire card below in one response.

# MMA DASHBOARD CARD RESPONSE CONTRACT v4

This v4 contract overrides any older response format or formatting habit in this conversation. Do not imitate earlier UFC, PFL, ONE, BKFC, LFA, or DWCS replies. Use this same structure for every promotion and every fight. Start directly with Fight 1: no preamble, alternate layout, JSON, code fence, or closing commentary.

## Research standard

- Use current web research and prefer official or reputable MMA sources.
- Verify records, finish totals, recent form, opponent quality, promotion history, style, relevant statistics, injuries, late replacements, cancellations/rebookings, and promotion-specific rules.
- Treat CARD DATA as useful provider-fed context, not guaranteed truth. Resolve conflicts and label missing or thin evidence instead of estimating.
- Judge opponent quality from actual records and demonstrated level, not name recognition alone.
- Verify hometown, residence, and current training-camp connections to the event area. A local connection is context, never an automatic edge.
- Reach an independent conclusion. Separate the most likely winner from whether the available price is worth betting.
- Use process_diagnostics quietly. Samples below 20 completed leans or tracked-close comparisons are descriptive only. Do not add a process-diagnostics section.

## Required fight format

Analyze every CARD DATA fight exactly once and in card order. Copy each fight's exact dashboard_import_key into its heading. Leave one blank line between sections. Do not rename, merge, omit, or reorder the five headings below.
The complete handicap must remain under the exact Matchup read heading so FightCenter can persist and render it on the correct matchup.

## Fight [card order]: [Fighter A] vs [Fighter B] [key=exact dashboard_import_key]

### Snapshot
| | [Fighter A] | [Fighter B] |
|---|---|---|
| Style | [short style label] | [short style label] |
| Record | [W-L-D or unknown] | [W-L-D or unknown] |
| KO/TKO wins | [integer or unknown] | [integer or unknown] |
| Submission wins | [integer or unknown] | [integer or unknown] |

### Matchup read
[Write a complete 140–220 word handicap in two short paragraphs. Cover recent form; relevant wins and losses; promotion experience; opponent quality, including whether recent opponents had winning records; method patterns; the style interaction; likely tactics and fight shape; and the clearest transferable edge. Mention a meaningful cancelled/rebooked bout or incomplete history when relevant. This section is mandatory even when evidence is thin.]

### Paths & risks
- **[Fighter A] win path:** [Specific realistic path.]
- **[Fighter B] win path:** [Specific realistic path.]
- **Reliability:** [Strong, mixed, or thin, with one sentence explaining evidence quality and whether the projected winner can consistently reach the needed condition.]
- **Volatility:** [Low, medium, or high fight/fighter volatility—not market movement—with one sentence explaining power, durability, cardio, decision dependence, rules, or limited-tape risk.]
- **Confidence limiter:** [Strongest evidence-based reason the read could fail.]

### Context
- **Local/camp:** [Verified connection and its actual relevance, or No verified local connection.]
- **Late news:** [Injury, replacement, weight-cut, layoff, cancellation/rebooking, or None found.]
- **Promotion lens:** [One promotion-specific factor that genuinely matters, or None material.]

### Verdict & price
- **Pick:** [Fighter name or Pass]
- **Win probability:** [Whole-number percentage before vig]
- **Fair moneyline:** [American odds derived from that probability]
- **Buy at:** [A more favorable threshold than the fair line that preserves a real edge]
- **Rank:** [A, B, C, or D]
- **Betting assessment:** [Bet, Wait, or Pass, tied to the best supplied current price]

Rank meaning: A = strongest evidence and price combination; B = playable with a clear edge; C = lean or price-dependent; D = pass or insufficient edge. Thin evidence or high volatility cannot receive A.

## Card Summary

- Rank the strongest betting leans from best to weakest.
- List fights to pass or wait on.
- Note any justified underdog, total, or method angle.
- List late-news or information items still worth monitoring.

## Dashboard Import

After the Card Summary, output exactly two single lines for every fight in the same card order. Copy the exact dashboard_import_key into both lines. Do not wrap these lines in a code block and do not place a semicolon inside a value.

**Dashboard facts [key=exact dashboard_import_key]:** A style=[short label]; B style=[short label]; A record=[W-L-D or unknown]; B record=[W-L-D or unknown]; A KO/TKO wins=[integer or unknown]; A submission wins=[integer or unknown]; B KO/TKO wins=[integer or unknown]; B submission wins=[integer or unknown]

**Decision data [key=exact dashboard_import_key]:** pick=[fighter_a, fighter_b, or pass]; win probability=[whole number 1-99]; fair moneyline=[American odds]; buy at=[American odds]; rank=[A, B, C, or D]; reliability=[strong, mixed, or thin]; volatility=[low, medium, or high]; betting assessment=[short value]; win path=[short projected-winner path]; upset path=[short opponent disruption path]; confidence limiter=[short reason]

Use concise style labels such as range striker, pressure wrestler, submission grappler, wrestle-boxer, or well-rounded. KO/TKO and submission totals mean verified career wins by those methods; write unknown rather than infer a total.

## Promotion emphasis

- UFC: UFC-level competition, reliable metrics, five-round experience, weight cuts, short notice, camps, and aging curves.
- DWCS/LFA: prospect readiness, regional competition, development risk, and limited-tape uncertainty.
- PFL: tournament or season incentives, turnaround time, rematches, cage, and rules context.
- ONE: exact sport and ruleset, hydration, judging, clinch, and grappling differences.
- BKFC: boxing fundamentals, bare-knuckle experience, power, chin, cuts, hand durability, pocket work, and volatility.

Before sending, silently verify: every CARD DATA fight appears once; every fight has the exact key in its heading; every fight has a complete Matchup read; every key has one Dashboard facts line and one Decision data line; no two events or matchups were combined.

CARD DATA
${JSON.stringify(context, null, 2)}`;
}
