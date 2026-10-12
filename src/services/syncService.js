import { supabase } from "../lib/supabase";
import { getPromotionKey } from "../config/promotions";

export async function getLatestSyncRun() {
  const { data, error } = await supabase
    .from("data_sync_runs")
    .select(`
      data_sync_run_id,
      started_at,
      finished_at,
      status,
      events_processed,
      fights_processed,
      results_processed,
      odds_status,
      summary
    `)
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();

  if (error) {
    throw error;
  }

  return data;
}

export async function getLatestHistoryMaintenanceRun() {
  const { data, error } = await supabase
    .from("history_maintenance_runs")
    .select(`
      history_maintenance_run_id,
      started_at,
      finished_at,
      status,
      fighters_checked,
      histories_found,
      confirmed_debuts,
      unavailable_histories,
      needs_review,
      summary
    `)
    .order("started_at", { ascending: false })
    .limit(1)
    .maybeSingle();
  if (error) throw error;
  return data;
}

export async function getUpcomingHistoryCoverage() {
  const today = new Date().toISOString().slice(0, 10);
  const { data, error } = await supabase
    .from("fighter_history_coverage")
    .select(`
      fighter_id,
      coverage_status,
      record_summary,
      coverage_note,
      source_used,
      last_checked_at,
      next_event_name,
      next_event_date,
      promotion_name,
      fighter:fighters!fighter_history_coverage_fighter_id_fkey (full_name)
    `)
    .gte("next_event_date", today)
    .in("coverage_status", [
      "confirmed_debut",
      "partial_history",
      "regional_history_unavailable",
      "history_unavailable",
      "needs_review",
    ])
    .order("next_event_date", { ascending: true });
  if (error) throw error;
  return (data ?? []).filter((entry) => getPromotionKey(entry.promotion_name));
}

async function localSyncRequest(options = {}) {
  const response = await fetch("/api/local-sync", options);
  const payload = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(payload.error ?? "Could not communicate with the local sync runner.");
  }

  return payload;
}

export function getLocalSyncState() {
  return localSyncRequest();
}

export function startDataSync(scope = "all") {
  return localSyncRequest({
    method: "POST",
    headers: {
      "X-MMA-Dashboard": "1",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ scope }),
  });
}
