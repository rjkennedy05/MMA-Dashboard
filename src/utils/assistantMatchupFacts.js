function normalizeName(value) {
  return String(value ?? "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[’']/g, "")
    .replace(/[^a-zA-Z0-9]+/g, " ")
    .trim()
    .toLowerCase();
}

function namesEquivalent(left, right) {
  if (!left || !right) {
    return false;
  }

  if (left === right) {
    return true;
  }

  const leftTokens = left.split(" ");
  const rightTokens = right.split(" ");
  const shorter = leftTokens.length <= rightTokens.length ? leftTokens : rightTokens;
  const longer = leftTokens.length <= rightTokens.length ? rightTokens : leftTokens;

  return (
    shorter.length >= 2
    && shorter.at(-1) === longer.at(-1)
    && shorter.every((token) => longer.includes(token))
  );
}

function stripMarkdown(value) {
  return String(value ?? "")
    .replace(/\[([^\]]+)]\([^\s)]+(?:\s+"[^"]*")?\)/g, "$1")
    .replace(/[*_`]/g, "")
    .trim();
}

function isUnknown(value) {
  return /^(unknown|unavailable|n\/?a|not available|not found)$/i.test(
    stripMarkdown(value).replace(/[.;,]+$/g, "").trim()
  );
}

function cleanValue(value) {
  return stripMarkdown(value)
    .replace(/^\s*[:=|\-–—]+\s*/, "")
    .replace(/\s*[;|\-–—]+\s*$/g, "")
    .trim();
}

function parseCount(value) {
  const cleaned = cleanValue(value);
  if (!cleaned || isUnknown(cleaned)) {
    return null;
  }

  const match = cleaned.match(/^\s*(\d+)\b/);
  const count = match ? Number(match[1]) : Number.NaN;
  return Number.isInteger(count) && count >= 0 ? count : null;
}

function parseRecord(value) {
  const cleaned = cleanValue(value);
  if (!cleaned || isUnknown(cleaned)) {
    return "";
  }

  const match = cleaned.match(/\b(\d+)\s*[-–—]\s*(\d+)(?:\s*[-–—]\s*(\d+))?/);
  if (!match) {
    return cleaned;
  }

  return `${match[1]}-${match[2]}-${match[3] ?? "0"}`;
}

const LABEL_PATTERN = /\b(?:fighter\s+)?([ab])\s+(style|record|ko(?:\s*\/\s*tko)?\s+wins?|knockout\s+wins?|submission\s+wins?|sub\s+wins?)\b/gi;

const DECISION_LABEL_PATTERN = /\b(pick|win\s+probability|fair\s+moneyline|buy\s+at|rank|reliability|volatility|betting\s+assessment|win\s+path|upset\s+path|confidence\s+limiter)\s*=/gi;

function fieldForLabel(side, label) {
  const prefix = side.toLowerCase() === "a" ? "fighter_a" : "fighter_b";
  const normalized = label.toLowerCase().replace(/\s+/g, " ");

  if (normalized === "style") {
    return `${prefix}_style`;
  }
  if (normalized === "record") {
    return `${prefix}_record_summary`;
  }
  if (normalized.includes("submission") || normalized.startsWith("sub ")) {
    return `${prefix}_submission_wins`;
  }
  return `${prefix}_ko_wins`;
}

function parseFields(text) {
  const cleaned = stripMarkdown(text);
  const matches = [...cleaned.matchAll(LABEL_PATTERN)];
  const facts = {};

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const nextMatch = matches[index + 1];
    const field = fieldForLabel(match[1], match[2]);
    const rawValue = cleaned.slice(
      match.index + match[0].length,
      nextMatch?.index ?? cleaned.length
    );
    const value = cleanValue(rawValue);

    if (field.endsWith("_style")) {
      facts[field] = isUnknown(value) ? "" : value;
    } else if (field.endsWith("_record_summary")) {
      facts[field] = parseRecord(value);
    } else {
      facts[field] = parseCount(value);
    }
  }

  return facts;
}

function parseDecisionFields(text) {
  const cleaned = stripMarkdown(text);
  const matches = [...cleaned.matchAll(DECISION_LABEL_PATTERN)];
  const fields = {};

  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const nextMatch = matches[index + 1];
    const label = match[1].toLowerCase().replace(/\s+/g, " ");
    const rawValue = cleaned.slice(
      match.index + match[0].length,
      nextMatch?.index ?? cleaned.length
    );
    const value = cleanValue(rawValue);

    if (label === "pick") {
      const normalizedValue = value.toLowerCase().replace(/\s+/g, "_");
      const normalized = {
        fightera: "fighter_a",
        fighterb: "fighter_b",
      }[normalizedValue] ?? normalizedValue;
      if (["fighter_a", "fighter_b", "pass"].includes(normalized)) {
        fields.assistant_pick = normalized;
      }
    } else if (label === "win probability") {
      const probability = Number(value.match(/\d{1,2}/)?.[0]);
      if (Number.isInteger(probability) && probability >= 1 && probability <= 99) {
        fields.assistant_win_probability = probability;
      }
    } else if (label === "fair moneyline") {
      const odds = Number(rawValue.match(/[+-]?\d+/)?.[0]);
      if (Number.isInteger(odds) && (odds <= -100 || odds >= 100)) {
        fields.assistant_fair_moneyline = odds;
      }
    } else if (label === "buy at") {
      const odds = Number(rawValue.match(/[+-]?\d+/)?.[0]);
      if (Number.isInteger(odds) && (odds <= -100 || odds >= 100)) {
        fields.assistant_target_price = odds;
      }
    } else if (label === "rank") {
      const rank = value.toUpperCase().replace(/[^A-D]/g, "").slice(0, 1);
      if (rank) fields.assistant_rank = rank;
    } else if (label === "reliability") {
      const reliability = value.toLowerCase();
      if (["strong", "mixed", "thin"].includes(reliability)) {
        fields.assistant_reliability = reliability;
      }
    } else if (label === "volatility") {
      const volatility = value.toLowerCase();
      if (["low", "medium", "high"].includes(volatility)) {
        fields.assistant_volatility = volatility;
      }
    } else if (label === "betting assessment") {
      fields.assistant_betting_assessment = value;
    } else if (label === "win path") {
      fields.assistant_win_path = value;
    } else if (label === "upset path") {
      fields.assistant_upset_path = value;
    } else if (label === "confidence limiter") {
      fields.assistant_confidence_limiter = value;
    }
  }

  return fields;
}

function parseDashboardBlock(lines) {
  const markerIndex = lines.findIndex((line) => /dashboard\s+facts?/i.test(line));
  const fallbackText = lines.slice(0, 14).join("\n");
  const fallbackLabelCount = [...stripMarkdown(fallbackText).matchAll(LABEL_PATTERN)].length;

  if (markerIndex === -1 && fallbackLabelCount < 4) {
    return null;
  }

  const sourceLines = markerIndex >= 0 ? lines.slice(markerIndex, markerIndex + 14) : lines.slice(0, 14);
  const block = [];

  for (const [index, line] of sourceLines.entries()) {
    if (
      index > 0
      && /^\s*(?:#{1,6}\s*)?(?:[-*]\s*)?\*{0,2}(?:snapshot|matchup read|independent matchup read|win paths|risk check|strongest counterargument|price check|projected winner|estimated winner|win probability|estimated win probability|fair moneyline|betting assessment|card summary|.+? win condition)\b/i.test(line)
    ) {
      break;
    }
    block.push(line);
  }

  const text = block
    .join("\n")
    .replace(/^.*?dashboard\s+facts?\s*:?/i, "");
  const facts = {
    ...parseFields(text),
    ...parseDecisionFields(text),
  };
  return Object.keys(facts).length > 0 ? facts : null;
}

function cleanHeading(value) {
  return stripMarkdown(value)
    .replace(/^#{1,6}\s*/, "")
    .replace(/^\s*[-*]\s*/, "")
    .replace(/^\s*(?:fight\s*)?(?:#\s*)?\d+\s*[.):\-–—]\s*/i, "")
    .trim();
}

function parseSections(analysis) {
  const sections = [];
  let current = null;

  for (const line of String(analysis ?? "").split(/\r?\n/)) {
    const importKey = parseImportKey(line);
    const cleaned = cleanHeading(line)
      .replace(/\s*\[\s*(?:key|fight[_\s-]*id)\s*=\s*[^\]]+\]\s*$/i, "")
      .trim();

    if (/^(?:card summary|dashboard import)\b/i.test(cleaned)) {
      current = null;
      continue;
    }

    const heading = cleaned.match(/^(.+?)\s+(?:vs?\.?|versus)\s+(.+?)\s*$/i);
    if (heading) {
      current = {
        fighterA: normalizeName(heading[1]),
        fighterB: normalizeName(heading[2]),
        importKey,
        lines: [],
      };
      sections.push(current);
      continue;
    }

    if (
      importKey
      && /^\s*#{1,6}\s+/.test(line)
      && !/(?:dashboard\s+facts?|decision\s+data)/i.test(line)
    ) {
      current = {
        fighterA: "",
        fighterB: "",
        importKey,
        lines: [],
      };
      sections.push(current);
      continue;
    }

    current?.lines.push(line);
  }

  return sections;
}

function narrativeStartIndex(lines) {
  const headingIndex = lines.findIndex((line) => {
    const heading = cleanHeading(line).replace(/[:\s]+$/g, "");
    return /^(?:matchup read|full matchup read|independent matchup read|fight analysis|local connection|local edge check)(?:\s*:|$)/i.test(heading);
  });

  if (headingIndex >= 0) {
    return headingIndex;
  }

  const factsIndex = lines.findIndex((line) => /dashboard\s+facts?/i.test(line));
  return factsIndex >= 0 ? factsIndex + 1 : 0;
}

export function extractAssistantMatchupAnalysis(analysis, fight) {
  if (!analysis || !fight?.fight_id) {
    return "";
  }

  const sections = parseSections(analysis);
  const importKey = String(fight.fight_id);
  const fighterA = normalizeName(fight.fighter_a?.full_name);
  const fighterB = normalizeName(fight.fighter_b?.full_name);
  const section = sections.find((entry) => entry.importKey === importKey)
    ?? sections.find((entry) =>
    entry.lines.some((line) => parseImportKey(line) === importKey)
  ) ?? sections.find(
    (entry) =>
      (namesEquivalent(entry.fighterA, fighterA) && namesEquivalent(entry.fighterB, fighterB))
      || (namesEquivalent(entry.fighterA, fighterB) && namesEquivalent(entry.fighterB, fighterA))
  );

  if (!section) {
    return "";
  }

  const startIndex = narrativeStartIndex(section.lines);
  return section.lines
    .slice(startIndex)
    .filter((line) => !/(?:dashboard\s+facts?|decision\s+data)\s*\[/i.test(line))
    .filter((line) => !/^\s*```/.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function parseImportKey(line) {
  return String(line ?? "").match(
    /\[\s*(?:key|fight[_\s-]*id)\s*=\s*([^\]]+)\]/i
  )?.[1]?.trim() ?? null;
}

function parseFactBlocks(analysis) {
  const lines = String(analysis ?? "").split(/\r?\n/);
  const markerIndexes = lines
    .map((line, index) => (/dashboard\s+facts?/i.test(line) ? index : -1))
    .filter((index) => index >= 0);

  return markerIndexes.flatMap((markerIndex, blockIndex) => {
    const nextMarker = markerIndexes[blockIndex + 1] ?? lines.length;
    const endIndex = Math.min(nextMarker, markerIndex + 16);
    const blockLines = lines.slice(markerIndex, endIndex);
    const facts = parseDashboardBlock(blockLines);

    if (!facts) {
      return [];
    }

    return [{
      facts,
      importKey: parseImportKey(lines[markerIndex]),
      context: lines.slice(Math.max(0, markerIndex - 8), markerIndex).join("\n"),
    }];
  });
}

function fightMatchesText(fight, text) {
  const normalizedText = normalizeName(text);
  const fighterA = normalizeName(fight.fighter_a?.full_name);
  const fighterB = normalizeName(fight.fighter_b?.full_name);

  if (!fighterA || !fighterB) {
    return false;
  }

  if (normalizedText.includes(fighterA) && normalizedText.includes(fighterB)) {
    return true;
  }

  const heading = cleanHeading(text).match(/^(.+?)\s+(?:vs?\.?|versus)\s+(.+?)\s*$/i);
  if (!heading) {
    return false;
  }

  const left = normalizeName(heading[1]);
  const right = normalizeName(heading[2]);
  return (
    (namesEquivalent(left, fighterA) && namesEquivalent(right, fighterB))
    || (namesEquivalent(left, fighterB) && namesEquivalent(right, fighterA))
  );
}

function swapFacts(facts) {
  const swapped = {};

  for (const [key, value] of Object.entries(facts)) {
    if (key.startsWith("fighter_a_")) {
      swapped[key.replace("fighter_a_", "fighter_b_")] = value;
    } else if (key.startsWith("fighter_b_")) {
      swapped[key.replace("fighter_b_", "fighter_a_")] = value;
    } else if (key === "assistant_pick" && value === "fighter_a") {
      swapped[key] = "fighter_b";
    } else if (key === "assistant_pick" && value === "fighter_b") {
      swapped[key] = "fighter_a";
    } else {
      swapped[key] = value;
    }
  }

  return swapped;
}

export function inspectAssistantMatchupFacts(analysis, fights) {
  if (!analysis || !Array.isArray(fights) || fights.length === 0) {
    return {
      updates: [],
      unmatchedFights: fights ?? [],
      sectionCount: 0,
      factBlockCount: 0,
      matchStrategy: "none",
    };
  }

  const sections = parseSections(analysis);
  const factBlocks = parseFactBlocks(analysis);
  const updates = [];
  const unmatchedFights = [];
  const usedBlockIndexes = new Set();
  let matchStrategy = "headings";

  for (const fight of fights) {
    const fighterA = normalizeName(fight.fighter_a?.full_name);
    const fighterB = normalizeName(fight.fighter_b?.full_name);
    const section = sections.find(
      (entry) => entry.importKey === String(fight.fight_id)
    ) ?? sections.find(
      (entry) =>
        (namesEquivalent(entry.fighterA, fighterA) && namesEquivalent(entry.fighterB, fighterB))
        || (namesEquivalent(entry.fighterA, fighterB) && namesEquivalent(entry.fighterB, fighterA))
    );
    let facts = section ? parseDashboardBlock(section.lines) : null;
    const narrative = extractAssistantMatchupAnalysis(analysis, fight);
    let reversed = section?.fighterA && section?.fighterB
      ? namesEquivalent(section.fighterA, fighterB)
        && namesEquivalent(section.fighterB, fighterA)
      : false;

    if (!facts) {
      const keyedBlockIndex = factBlocks.findIndex(
        (block, index) => !usedBlockIndexes.has(index)
          && block.importKey
          && String(block.importKey) === String(fight.fight_id)
      );
      const contextualBlockIndex = keyedBlockIndex >= 0
        ? keyedBlockIndex
        : factBlocks.findIndex(
          (block, index) => !usedBlockIndexes.has(index)
            && fightMatchesText(fight, block.context)
        );

      if (contextualBlockIndex >= 0) {
        facts = factBlocks[contextualBlockIndex].facts;
        usedBlockIndexes.add(contextualBlockIndex);
        reversed = false;
        matchStrategy = keyedBlockIndex >= 0 ? "keys" : "nearby names";
      }
    }

    if (!facts && !narrative) {
      unmatchedFights.push(fight);
      continue;
    }

    updates.push({
      fight_id: fight.fight_id,
      ...(facts ? (reversed ? swapFacts(facts) : facts) : {}),
      ...(narrative ? { assistant_matchup_analysis: narrative } : {}),
    });
  }

  if (
    updates.length === 0
    && factBlocks.length === fights.length
    && factBlocks.length > 0
  ) {
    matchStrategy = "card order";
    return {
      updates: fights.map((fight, index) => ({
        fight_id: fight.fight_id,
        ...factBlocks[index].facts,
        ...(extractAssistantMatchupAnalysis(analysis, fight)
          ? { assistant_matchup_analysis: extractAssistantMatchupAnalysis(analysis, fight) }
          : {}),
      })),
      unmatchedFights: [],
      sectionCount: sections.length,
      factBlockCount: factBlocks.length,
      matchStrategy,
    };
  }

  return {
    updates,
    unmatchedFights,
    sectionCount: sections.length,
    factBlockCount: factBlocks.length,
    matchStrategy,
  };
}

export function parseAssistantMatchupFacts(analysis, fights) {
  return inspectAssistantMatchupFacts(analysis, fights).updates
    .map(({ assistant_matchup_analysis: _narrative, ...facts }) => facts)
    .filter((facts) => Object.keys(facts).length > 1);
}

export function parseRecordWins(recordSummary) {
  const wins = String(recordSummary ?? "").trim().match(/^(\d+)\s*[-–]/)?.[1];
  return wins === undefined ? null : Number(wins);
}

export function finishSummary({ koWins, submissionWins, recordSummary }) {
  if (!Number.isInteger(koWins) || !Number.isInteger(submissionWins)) {
    return "—";
  }

  const finishes = koWins + submissionWins;
  const wins = parseRecordWins(recordSummary);
  if (!Number.isInteger(wins) || wins <= 0 || finishes > wins) {
    return `${finishes} total`;
  }

  return `${finishes} of ${wins} wins (${Math.round((finishes / wins) * 100)}%)`;
}
