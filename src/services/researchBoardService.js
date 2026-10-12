import { supabase } from "../lib/supabase";
import { getLatestMoneylinesForFights } from "./oddsService";

function one(value) {
  return Array.isArray(value) ? value[0] ?? null : value ?? null;
}

export async function getUpcomingResearchBoard() {
  const { data, error } = await supabase
    .from("fight_research")
    .select(`
      *,
      fights!inner (
        fight_id,
        event_id,
        fight_order,
        fight_status,
        fighter_a_id,
        fighter_b_id,
        fighter_a:fighters!fights_fighter_a_id_fkey (fighter_id, full_name),
        fighter_b:fighters!fights_fighter_b_id_fkey (fighter_id, full_name),
        events!inner (
          event_id,
          event_name,
          event_date,
          promotions (name)
        )
      )
    `);

  if (error) throw error;

  const today = new Date().toISOString().slice(0, 10);
  const rows = (data ?? []).flatMap((research) => {
    const fight = one(research.fights);
    const event = one(fight?.events);
    const promotion = one(event?.promotions);
    const fighterA = one(fight?.fighter_a);
    const fighterB = one(fight?.fighter_b);
    const hasResearch = Boolean(
      research.user_lean
      || research.assistant_pick
      || (research.research_status && research.research_status !== "not_started")
    );

    if (!fight || !event || event.event_date < today || !hasResearch) {
      return [];
    }

    return [{
      ...research,
      fight: {
        ...fight,
        fighter_a: fighterA,
        fighter_b: fighterB,
        events: { ...event, promotions: promotion },
      },
    }];
  });

  const oddsByFight = await getLatestMoneylinesForFights(
    rows.map((row) => row.fight.fight_id)
  );

  return { rows, oddsByFight };
}
