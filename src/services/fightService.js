import { readRows } from "./readRows";
import { supabase } from "../lib/supabase";
import { dedupeEventFights } from "../utils/fights";

export async function getFightsByEvent(eventId) {
  if (!eventId) {
    return [];
  }

  const data=await readRows(()=>supabase
    .from("fights")
    .select(`
      fight_id,
      event_id,
      fighter_a_id,
      fighter_b_id,
      weight_class_id,
      ruleset,
      bout_type,
      scheduled_rounds,
      fight_order,
      fight_status,
      winner_id,
      result_type,
      method,
      finish_round,
      finish_time_seconds,
      is_title_fight,

      events (
        event_name,
        event_date,
        event_start_time,
        watch_platform,
        city,
        state_region,
        country,
        promotions (
          name
        )
      ),

      fighter_a:fighters!fights_fighter_a_id_fkey (
        fighter_id,
        full_name,
        nickname,
        date_of_birth,
        height_inches,
        reach_inches,
        stance,
        nationality,
        record_summary,
        age_snapshot,
        profile_updated_at,
        image_url,
        profile_source:data_sources!fighters_profile_source_id_fkey (
          name
        ),
        status
      ),

      fighter_b:fighters!fights_fighter_b_id_fkey (
        fighter_id,
        full_name,
        nickname,
        date_of_birth,
        height_inches,
        reach_inches,
        stance,
        nationality,
        record_summary,
        age_snapshot,
        profile_updated_at,
        image_url,
        profile_source:data_sources!fighters_profile_source_id_fkey (
          name
        ),
        status
      ),

      weight_classes (
        name
      )
    `)
    .eq("event_id", eventId)
    .order("fight_order", {
      ascending: true,
    }),"fight_id");
  const error=null;

  if (error) {
    throw error;
  }

  return dedupeEventFights(data ?? []);
}
