import { supabase } from "../lib/supabase";

export async function getEventResearch(eventId) {
  if (!eventId) {
    return null;
  }

  const { data, error } = await supabase
    .from("event_research")
    .select("*")
    .eq("event_id", eventId)
    .maybeSingle();

  if (error) {
    throw error;
  }

  return data;
}

export async function saveEventAnalysis(eventId, assistantCardAnalysis) {
  if (!eventId) {
    throw new Error("Select an event before saving card analysis.");
  }

  const { data, error } = await supabase
    .from("event_research")
    .upsert(
      {
        event_id: eventId,
        assistant_card_analysis: assistantCardAnalysis,
        updated_at: new Date().toISOString(),
      },
      { onConflict: "event_id" }
    )
    .select("*")
    .single();

  if (error) {
    throw error;
  }

  return data;
}
