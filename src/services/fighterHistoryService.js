import { readRows } from "./readRows";
import { mergeFighterHistories } from "../utils/historyMerge";
import { supabase } from "../lib/supabase";

const COVERAGE_SELECT = `
      fighter_id,
      history_fighter_id,
      coverage_status,
      record_summary,
      known_bout_count,
      source_used,
      coverage_note,
      last_checked_at,
      next_check_at
    `;

const OFFICIAL_SELECT = `
      fight_id,
      event_id,
      fighter_a_id,
      fighter_b_id,
      fight_status,
      ruleset,
      winner_id,
      result_type,
      method,
      finish_round,
      finish_time_seconds,
      is_title_fight,
      events (
        event_name,
        event_date,
        promotions (name)
      ),
      fighter_a:fighters!fights_fighter_a_id_fkey (
        fighter_id,
        full_name,
        record_summary
      ),
      fighter_b:fighters!fights_fighter_b_id_fkey (
        fighter_id,
        full_name,
        record_summary
      ),
      weight_classes (name)
    `;

const FALLBACK_SELECT = `
      fighter_history_entry_id,
      fighter_id,
      source_id,
      event_name,
      event_date,
      promotion_name,
      opponent_name,
      opponent_record,
      outcome,
      method,
      finish_round,
      finish_time_seconds,
      fight_status,
      is_title_fight,
      source_url
    `;

function recordWins(record) {
  const match = String(record ?? "").match(/^(\d+)\s*[-–]/);
  return match ? Number(match[1]) : null;
}

function recordLosses(record) {
  const match = String(record ?? "").match(/^\d+\s*[-–]\s*(\d+)/);
  return match ? Number(match[1]) : null;
}

function opponentRecordQuality(record) {
  const wins = recordWins(record);
  const losses = recordLosses(record);
  if (!Number.isInteger(wins) || !Number.isInteger(losses)) return "unknown";
  if (wins > losses) return "winning";
  if (wins === losses) return "even";
  return "losing";
}

function fighterOutcome(fight, fighterId) {
  if (fight.fight_status === "cancelled") return "CANCELLED";
  if (fight.fight_status === "draw" || fight.result_type === "draw") return "D";
  if (fight.fight_status === "no_contest" || fight.result_type === "no_contest") return "NC";
  if (fight.fight_status !== "completed") return "SCHEDULED";
  if (!fight.winner_id) return "—";
  return Number(fight.winner_id) === Number(fighterId) ? "W" : "L";
}

function normalizeHistoryFight(fight, fighterId) {
  const fighterIsA = Number(fight.fighter_a_id) === Number(fighterId);
  const opponent = fighterIsA ? fight.fighter_b : fight.fighter_a;
  return {
    fightId: fight.fight_id,
    eventId: fight.event_id,
    date: fight.events?.event_date ?? null,
    eventName: fight.events?.event_name ?? "Unknown event",
    promotion: fight.events?.promotions?.name ?? "Unknown promotion",
    opponent,
    opponentRecord: opponent?.record_summary ?? null,
    opponentRecordQuality: opponentRecordQuality(opponent?.record_summary),
    outcome: fighterOutcome(fight, fighterId),
    method: fight.method ?? null,
    round: fight.finish_round ?? null,
    timeSeconds: fight.finish_time_seconds ?? null,
    status: fight.fight_status,
    ruleset: fight.ruleset??"MMA",
    titleFight: Boolean(fight.is_title_fight),
    weightClass: fight.weight_classes?.name ?? null,
  };
}

export function promotionHistorySummary(history) {
  const grouped = new Map();
  for (const fight of history ?? []) {
    const current = grouped.get(fight.promotion) ?? {
      promotion: fight.promotion,
      wins: 0,
      losses: 0,
      draws: 0,
      noContests: 0,
      cancelled: 0,
    };
    if (fight.outcome === "W") current.wins += 1;
    if (fight.outcome === "L") current.losses += 1;
    if (fight.outcome === "D") current.draws += 1;
    if (fight.outcome === "NC") current.noContests += 1;
    if (fight.outcome === "CANCELLED") current.cancelled += 1;
    grouped.set(fight.promotion, current);
  }
  return [...grouped.values()].sort(
    (left, right) =>
      (right.wins + right.losses + right.draws + right.noContests)
      - (left.wins + left.losses + left.draws + left.noContests)
  );
}

function normalizeFallbackFight(entry) {
  return {
    fightId: `fallback-${entry.fighter_history_entry_id}`,
    eventId: null,
    date: entry.event_date ?? null,
    eventName: entry.event_name ?? "Unknown event",
    promotion: entry.promotion_name ?? "Regional/other",
    opponent: {
      full_name: entry.opponent_name ?? "Opponent unavailable",
      record_summary: entry.opponent_record ?? null,
    },
    opponentRecord: entry.opponent_record ?? null,
    opponentRecordQuality: opponentRecordQuality(entry.opponent_record),
    outcome: entry.outcome ?? "—",
    method: entry.method ?? null,
    round: entry.finish_round ?? null,
    timeSeconds: entry.finish_time_seconds ?? null,
    status: entry.fight_status ?? "completed",
    titleFight: Boolean(entry.is_title_fight),
    weightClass: null,
    sourceUrl: entry.source_url ?? null,
    sourceType: "fallback",
  };
}

export async function getFighterHistoryRecords(fighterIds,excludeFightId=null) {
  const ids=[...new Set((fighterIds??[]).filter(Boolean).map(Number))];
  if(!ids.length)return {};
  const coverageRows=await readRows(()=>supabase.from("fighter_history_coverage").select(COVERAGE_SELECT).in("fighter_id",ids),"fighter_id");
  const coverageById=Object.fromEntries(coverageRows.map(c=>[c.fighter_id,c]));
  const officialIds=[...new Set(ids.flatMap(id=>[id,coverageById[id]?.history_fighter_id]).filter(Boolean))];
  const [officialRows,fallbackRows]=await Promise.all([
    readRows(()=>supabase.from("fights").select(OFFICIAL_SELECT).or(`fighter_a_id.in.(${officialIds.join(",")}),fighter_b_id.in.(${officialIds.join(",")})`),"fight_id"),
    readRows(()=>supabase.from("fighter_history_entries").select(FALLBACK_SELECT).in("fighter_id",ids),"fighter_history_entry_id"),
  ]);
  return Object.fromEntries(ids.map(id=>{
    const linked=new Set([id,Number(coverageById[id]?.history_fighter_id)].filter(Boolean));
    const official=officialRows.filter(f=>Number(f.fight_id)!==Number(excludeFightId) && (linked.has(Number(f.fighter_a_id))||linked.has(Number(f.fighter_b_id))))
      .map(f=>normalizeHistoryFight(f,linked.has(Number(f.fighter_a_id))?f.fighter_a_id:f.fighter_b_id));
    const fallback=fallbackRows.filter(f=>Number(f.fighter_id)===id).map(normalizeFallbackFight);
    return [id,{history:mergeFighterHistories(official,fallback),coverage:coverageById[id]??null}];
  }));
}

export async function getFighterHistoryRecord(fighterId,excludeFightId=null) {
  if(!fighterId)return {history:[],coverage:null};
  return (await getFighterHistoryRecords([fighterId],excludeFightId))[fighterId];
}

export async function getFighterHistory(fighterId, excludeFightId = null) {
  const result = await getFighterHistoryRecord(fighterId, excludeFightId);
  return result.history;
}

export async function getMatchupHistoryRecords(fight) {
  if (!fight) {
    return {
      fighterA: { history: [], coverage: null },
      fighterB: { history: [], coverage: null },
    };
  }
  const records=await getFighterHistoryRecords([fight.fighter_a?.fighter_id,fight.fighter_b?.fighter_id],fight.fight_id);
  return {fighterA:records[fight.fighter_a?.fighter_id]??{history:[],coverage:null},
    fighterB:records[fight.fighter_b?.fighter_id]??{history:[],coverage:null}};
}

export async function getCardFighterHistories(fights) {
  const fighterIds = [...new Set(
    (fights ?? []).flatMap((fight) => [
      fight.fighter_a?.fighter_id,
      fight.fighter_b?.fighter_id,
    ]).filter(Boolean)
  )];
  const records=await getFighterHistoryRecords(fighterIds);
  return Object.fromEntries(Object.entries(records).map(([id,value])=>[id,value.history]));
}
