import { supabase } from "../lib/supabase";

export async function getFightResearch(fightId) {
  if (!fightId) {
    return null;
  }

  const { data, error } = await supabase
    .from("fight_research")
    .select("*")
    .eq("fight_id", fightId)
    .maybeSingle();

  if (error) {
    throw error;
  }

  return data;
}

export async function getFightResearchForFights(fightIds) {
  if (!Array.isArray(fightIds) || fightIds.length === 0) {
    return {};
  }

  const { data, error } = await supabase
    .from("fight_research")
    .select("*")
    .in("fight_id", fightIds);

  if (error) {
    throw error;
  }

  return Object.fromEntries(
    (data ?? []).map((research) => [research.fight_id, research])
  );
}

export async function getFightResearchCoverageForFights(fightIds) {
  if (!Array.isArray(fightIds) || fightIds.length === 0) {
    return {};
  }

  const { data, error } = await supabase
    .from("fight_research")
    .select("fight_id, research_status, user_lean, assistant_pick")
    .in("fight_id", fightIds);

  if (error) {
    throw error;
  }

  return Object.fromEntries(
    (data ?? []).map((research) => [research.fight_id, research])
  );
}

export async function saveAssistantMatchupFacts(matchupFacts) {
  if (!Array.isArray(matchupFacts) || matchupFacts.length === 0) {
    return [];
  }

  const updatedAt = new Date().toISOString();
  const payload = matchupFacts.map((facts) => ({
    ...facts,
    ...(facts.assistant_pick ? { assistant_snapshot_at: updatedAt } : {}),
    updated_at: updatedAt,
  }));
  const { data, error } = await supabase
    .from("fight_research")
    .upsert(payload, { onConflict: "fight_id" })
    .select("fight_id");

  if (error) {
    throw error;
  }

  return data ?? [];
}

export async function saveFightResearch(fightId, research) {
  if (!fightId) {
    throw new Error("Select a fight before saving research.");
  }

  const researchPayload = {
    fight_id: fightId,
    research_status: research.research_status,
    fighter_a_ratings: research.fighter_a_ratings,
    fighter_b_ratings: research.fighter_b_ratings,
    matchup_notes: research.matchup_notes,
    competition_notes: research.competition_notes,
    trend_notes: research.trend_notes,
    fighter_a_path: research.fighter_a_path,
    fighter_b_path: research.fighter_b_path,
    fighter_a_style: research.fighter_a_style?.trim() ?? "",
    fighter_b_style: research.fighter_b_style?.trim() ?? "",
    fighter_a_record_summary:
      research.fighter_a_record_summary?.trim() ?? "",
    fighter_b_record_summary:
      research.fighter_b_record_summary?.trim() ?? "",
    fighter_a_ko_wins:
      research.fighter_a_ko_wins === "" || research.fighter_a_ko_wins === null
        ? null
        : Number(research.fighter_a_ko_wins),
    fighter_a_submission_wins:
      research.fighter_a_submission_wins === ""
        || research.fighter_a_submission_wins === null
        ? null
        : Number(research.fighter_a_submission_wins),
    fighter_b_ko_wins:
      research.fighter_b_ko_wins === "" || research.fighter_b_ko_wins === null
        ? null
        : Number(research.fighter_b_ko_wins),
    fighter_b_submission_wins:
      research.fighter_b_submission_wins === ""
        || research.fighter_b_submission_wins === null
        ? null
        : Number(research.fighter_b_submission_wins),
    user_lean: research.user_lean || null,
    target_price: research.target_price || null,
    confidence: research.confidence || null,
    source_picks: research.source_picks,
    updated_at: new Date().toISOString(),
  };

  const { data: researchData, error: researchError } = await supabase
    .from("fight_research")
    .upsert(researchPayload, { onConflict: "fight_id" })
    .select("*")
    .single();

  if (researchError) {
    throw researchError;
  }

  return researchData;
}
