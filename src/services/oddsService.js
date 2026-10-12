import { readRows } from "./readRows";
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

  const batches=[];
  for(let index=0;index<fightIds.length;index+=25)batches.push(fightIds.slice(index,index+25));
  const responses=await Promise.all(batches.map(async(ids)=>{
    const {data,error}=await supabase.rpc("mma_moneyline_snapshot_summary",{p_fight_ids:ids});
    if(error)throw error;
    if(!Array.isArray(data))throw new Error("Moneyline snapshot was incomplete; existing prices were kept.");
    return data;
  }));
  const data=responses.flat();
  return buildMoneylineHistory(data ?? []);
}

export async function getMoneylineCoverageForFights(fightIds) {
  if (!Array.isArray(fightIds) || fightIds.length === 0) {
    return new Set();
  }

  const [fights,observations]=await Promise.all([
    readRows(()=>supabase.from("fights").select("fight_id,fighter_a_id,fighter_b_id").in("fight_id",fightIds),"fight_id"),
    readRows(()=>supabase.from("mma_odds_observations").select("observation_id,fight_id,fighter_id,sportsbook_key")
      .in("fight_id",fightIds).gte("observed_at",new Date(Date.now()-86400000).toISOString()),"observation_id"),
  ]);
  const pairs=new Map();
  for(const row of observations){const key=`${row.fight_id}:${row.sportsbook_key}`;
    if(!pairs.has(key))pairs.set(key,new Set());pairs.get(key).add(Number(row.fighter_id));}
  return new Set(fights.filter(f=>[...pairs.entries()].some(([key,sides])=>key.startsWith(`${f.fight_id}:`)
    && sides.has(Number(f.fighter_a_id))&&sides.has(Number(f.fighter_b_id)))).map(f=>Number(f.fight_id)));
}
