import { supabase } from "../lib/supabase";
import { buildMoneylineHistory } from "../utils/odds";

/**
 * Returns the first tracked, latest, and final tracked pre-fight moneyline
 * from each sportsbook
 * for every fighter in the supplied fights.
 *
 * Result shape:
 *
 * {
 *   [fightId]: {
 *     [fighterId]: [
 *       {
 *         sportsbook,
 *         opening_odds,
 *         american_odds,
 *         recorded_at
 *       }
 *     ]
 *   }
 * }
 */
export async function getLatestMoneylinesForFights(
  fightIds
) {
  if (!Array.isArray(fightIds) || fightIds.length === 0) {
    return {};
  }

  const { data, error } = await supabase
    .from("odds")
    .select(`
      odds_id,
      fight_id,
      fighter_id,
      sportsbook,
      sportsbook_key,
      american_odds,
      implied_probability,
      recorded_at,
      market_commence_time
    `)
    .in("fight_id", fightIds)
    .eq("market_type", "moneyline")
    .order("recorded_at", {
      ascending: false,
    });

  if (error) {
    throw error;
  }

  return buildMoneylineHistory(data ?? []);
}

export async function getMoneylineCoverageForFights(fightIds) {
  if (!Array.isArray(fightIds) || fightIds.length === 0) {
    return new Set();
  }

  const { data, error } = await supabase
    .from("odds")
    .select("fight_id")
    .in("fight_id", fightIds)
    .eq("market_type", "moneyline");

  if (error) {
    throw error;
  }

  return new Set((data ?? []).map((row) => Number(row.fight_id)));
}
