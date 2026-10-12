import { readRows } from "./readRows";
import { supabase } from "../lib/supabase";
import {
  buildProcessScorecard,
  buildTrackedCloseDiagnostics,
  summarizeLeanAccuracy,
} from "../utils/closingDiagnostics";
import { getLatestMoneylinesForFights } from "./oddsService";

function one(value) {
  return Array.isArray(value) ? value[0] ?? null : value ?? null;
}

function selectionName(side, fighterA, fighterB) {
  return side === "fighter_a"
    ? fighterA?.full_name
    : side === "fighter_b"
      ? fighterB?.full_name
      : null;
}

function mapFight(fight) {
  const event = one(fight?.events);
  const promotion = one(event?.promotions);
  const fighterA = one(fight?.fighter_a);
  const fighterB = one(fight?.fighter_b);

  return {
    fight,
    fight_id: fight?.fight_id ?? null,
    fight_status: fight?.fight_status ?? null,
    winner_id: fight?.winner_id ?? null,
    result_type: fight?.result_type ?? null,
    method: fight?.method ?? null,
    finish_round: fight?.finish_round ?? null,
    finish_time_seconds: fight?.finish_time_seconds ?? null,
    event_id: fight?.event_id ?? null,
    event_name: event?.event_name ?? "Unknown event",
    event_date: event?.event_date ?? null,
    promotion_name: promotion?.name ?? "Other",
    fighter_a: fighterA,
    fighter_b: fighterB,
  };
}

const FIGHT_SELECT = `
  fight_id,
  event_id,
  fight_order,
  fight_status,
  winner_id,
  result_type,
  method,
  finish_round,
  finish_time_seconds,
  fighter_a:fighters!fights_fighter_a_id_fkey (
    fighter_id,
    full_name
  ),
  fighter_b:fighters!fights_fighter_b_id_fkey (
    fighter_id,
    full_name
  ),
  events!inner (
    event_id,
    event_name,
    event_date,
    promotions (
      name
    )
  )
`;

async function getSingleBets(includeArchived = false) {
  let query = supabase
    .from("fight_research")
    .select(`
      fight_id,
      bet_side,
      bet_sportsbook,
      bet_price,
      stake_units,
      confidence,
      target_price,
      assistant_pick,
      assistant_win_probability,
      assistant_fair_moneyline,
      assistant_target_price,
      assistant_rank,
      assistant_reliability,
      assistant_volatility,
      settlement_status,
      settled_at,
      bet_archived_at,
      fights!inner (${FIGHT_SELECT})
    `)
    .not("bet_side", "is", null)
    .not("bet_price", "is", null)
    .gt("stake_units", 0);

  if (!includeArchived) {
    query = query.is("bet_archived_at", null);
  }

  const data = await readRows(()=>query, "fight_id");
  const error=null;

  if (error) {
    throw error;
  }

  return (data ?? []).map((row) => {
    const mapped = mapFight(one(row.fights));
    return {
      ...row,
      ...mapped,
      ticket_type: "single",
      bet_id: `single:${row.fight_id}`,
      selection_name: selectionName(
        row.bet_side,
        mapped.fighter_a,
        mapped.fighter_b
      ),
      event_ids: mapped.event_id === null ? [] : [mapped.event_id],
    };
  });
}

async function getParlayBets(includeArchived = false) {
  let query = supabase
    .from("bet_tickets")
    .select(`
      ticket_id,
      ticket_type,
      revision,
      ticket_label,
      bet_sportsbook,
      ticket_price,
      stake_units,
      settlement_status,
      settled_at,
      placed_at,
      archived_at,
      bet_legs (
        leg_id,
        selected_fighter_id,
        fight_id,
        bet_side,
        leg_price,
        leg_order,
        fights!inner (${FIGHT_SELECT})
      )
    `)
    .gt("stake_units", 0);

  if (!includeArchived) {
    query = query.is("archived_at", null);
  }

  const data = await readRows(()=>query,"ticket_id");
  const error=null;

  if (error) {
    throw error;
  }

  return (data ?? []).map((ticket) => {
    const legs = (ticket.bet_legs ?? [])
      .map((leg) => {
        const mapped = mapFight(one(leg.fights));
        return {
          ...leg,
          ...mapped,
          selection_name: selectionName(
            leg.bet_side,
            mapped.fighter_a,
            mapped.fighter_b
          ),
        };
      })
      .sort((a, b) => (a.leg_order ?? 0) - (b.leg_order ?? 0));
    const eventIds = [...new Set(legs.map((leg) => leg.event_id).filter(Boolean))];
    const eventNames = [...new Set(legs.map((leg) => leg.event_name))];
    const eventDates = legs.map((leg) => leg.event_date).filter(Boolean).sort();
    const promotions = [...new Set(legs.map((leg) => leg.promotion_name))];
    const primaryEventId = eventIds.length === 1 ? eventIds[0] : null;

    if (ticket.ticket_type === "single") {
      const leg=legs[0];
      if (!leg) throw new Error("Saved single has no leg; review the import before displaying results.");
      return {...leg,ticket_type:"single",ticket_id:ticket.ticket_id,revision:ticket.revision,
        bet_id:`ticket:${ticket.ticket_id}`,bet_sportsbook:ticket.bet_sportsbook,bet_price:ticket.ticket_price,
        stake_units:ticket.stake_units,settlement_status:ticket.settlement_status,settled_at:ticket.settled_at,
        placed_at:ticket.placed_at,archived_at:ticket.archived_at,event_ids:eventIds};
    }
    return {
      ticket_type: ticket.ticket_type,
      revision: ticket.revision,
      bet_id: `ticket:${ticket.ticket_id}`,
      ticket_id: ticket.ticket_id,
      ticket_label: ticket.ticket_label,
      bet_sportsbook: ticket.bet_sportsbook,
      bet_price: ticket.ticket_price,
      stake_units: ticket.stake_units,
      settlement_status: ticket.settlement_status,
      settled_at: ticket.settled_at,
      placed_at: ticket.placed_at,
      archived_at: ticket.archived_at,
      legs,
      event_ids: eventIds,
      event_id: primaryEventId,
      event_name:
        eventNames.length === 1
          ? eventNames[0]
          : `${eventNames.length} cards`,
      event_date: eventDates.at(-1) ?? null,
      promotion_name:
        promotions.length === 1 ? promotions[0] : "Multi-promotion",
      selection_name:
        ticket.ticket_label?.trim() || `${legs.length}-leg ML parlay`,
    };
  });
}

export async function getTrackedBets({ includeArchived = false } = {}) {
  const [singles, parlays] = await Promise.all([
    getSingleBets(includeArchived),
    getParlayBets(includeArchived),
  ]);

  return [...singles, ...parlays].sort(
    (a, b) =>
      (b.event_date ?? "").localeCompare(a.event_date ?? "")
      || (a.fight?.fight_order ?? 0) - (b.fight?.fight_order ?? 0)
      || String(b.bet_id).localeCompare(String(a.bet_id))
  );
}

export async function saveBetSettlement(bet, settlementStatus) {
  const isParlay = Boolean(bet?.ticket_id);
  const identifier = isParlay ? bet?.ticket_id : bet?.fight_id;
  if (!identifier) {
    throw new Error("A bet is required before it can be graded.");
  }

  const isPending = settlementStatus === "pending";
  const table = isParlay ? "bet_tickets" : "fight_research";
  const idColumn = isParlay ? "ticket_id" : "fight_id";
  let query=supabase
    .from(table)
    .update({
      settlement_status: settlementStatus,
      settled_at: isPending ? null : new Date().toISOString(),
      updated_at: new Date().toISOString(),
    })
    .eq(idColumn, identifier);
  if(isParlay)query=query.eq("revision",bet.revision);
  const {data,error}=await query.select(`${idColumn}, settlement_status, settled_at`).single();

  if (error) {
    throw error;
  }

  return data;
}

function validAmericanOdds(value) {
  const number = Number(value);
  return Number.isInteger(number) && (number <= -100 || number >= 100);
}

const SETTLEMENT_STATUSES = new Set(["pending", "win", "loss", "push", "void"]);

function validateTicketFields({ sportsbook, price, stakeUnits, settlementStatus = "pending" }) {
  if (!sportsbook?.trim()) {
    throw new Error("Select or enter the sportsbook used for this ticket.");
  }
  if (!validAmericanOdds(price)) {
    throw new Error("Enter valid American odds for this ticket.");
  }
  if (!(Number(stakeUnits) > 0)) {
    throw new Error("Enter a stake greater than zero units.");
  }
  if (!SETTLEMENT_STATUSES.has(settlementStatus)) {
    throw new Error("Select a valid ticket result.");
  }
}

export async function saveSingleBet({
  fightId,
  betSide,
  sportsbook,
  betPrice,
  stakeUnits,
}) {
  if (!fightId || !["fighter_a", "fighter_b"].includes(betSide)) {
    throw new Error("Select one fighter for the single bet.");
  }
  validateTicketFields({ sportsbook, price: betPrice, stakeUnits });

  return persistTicket({ticket_type:"single",bet_sportsbook:sportsbook.trim(),
    ticket_price:Number(betPrice),stake_units:Number(stakeUnits),request_id:crypto.randomUUID()},
    [{fight_id:fightId,bet_side:betSide,leg_price:Number(betPrice)}]);
}

export async function updateTrackedBet(bet, edits) {
  if (!bet?.bet_id) {
    throw new Error("Select a saved ticket to edit.");
  }

  const settlementStatus = edits.settlement_status ?? "pending";
  validateTicketFields({
    sportsbook: edits.bet_sportsbook,
    price: edits.bet_price,
    stakeUnits: edits.stake_units,
    settlementStatus,
  });

  const timestamp = new Date().toISOString();
  const settlement = {
    settlement_status: settlementStatus,
    settled_at: settlementStatus === "pending" ? null : timestamp,
    updated_at: timestamp,
  };

  if (!bet.ticket_id) {
    if (!["fighter_a", "fighter_b"].includes(edits.bet_side)) {
      throw new Error("Select the fighter used for this single bet.");
    }

    const { data, error } = await supabase
      .from("fight_research")
      .update({
        bet_side: edits.bet_side,
        bet_sportsbook: edits.bet_sportsbook.trim(),
        bet_price: Number(edits.bet_price),
        stake_units: Number(edits.stake_units),
        bet_archived_at: null,
        ...settlement,
      })
      .eq("fight_id", bet.fight_id)
      .select("fight_id")
      .single();

    if (error) throw error;
    return data;
  }

  const legs = bet.ticket_type==="single"
    ? [{fight_id:bet.fight_id,bet_side:edits.bet_side,leg_price:Number(edits.bet_price)}]
    : (edits.legs??[]).map(leg=>({fight_id:leg.fight_id ?? bet.legs.find(old=>old.leg_id===leg.leg_id)?.fight_id,
        bet_side:leg.bet_side,leg_price:Number(leg.leg_price)}));
  return persistTicket({ticket_type:bet.ticket_type,ticket_label:edits.ticket_label?.trim()??"",
    bet_sportsbook:edits.bet_sportsbook.trim(),ticket_price:Number(edits.bet_price),
    stake_units:Number(edits.stake_units),settlement_status:settlementStatus},legs,bet.ticket_id,bet.revision);
}

export async function deleteTrackedBet(bet) {
  if (!bet?.bet_id) {
    throw new Error("Select a saved ticket to delete.");
  }

  if (bet.ticket_id) {
    const { error } = await supabase
      .from("bet_tickets")
      .delete()
      .eq("ticket_id", bet.ticket_id);
    if (error) throw error;
    return;
  }

  const { error } = await supabase
    .from("fight_research")
    .update({
      bet_side: null,
      bet_sportsbook: "",
      bet_price: null,
      stake_units: null,
      settlement_status: "pending",
      settled_at: null,
      bet_archived_at: null,
      updated_at: new Date().toISOString(),
    })
    .eq("fight_id", bet.fight_id);
  if (error) throw error;
}

export async function resetCurrentBetPeriod() {
  const {data,error}=await supabase.rpc("mma_archive_bet_period");
  if(error) throw error;
  return data;
}

export async function saveParlayTicket({
  ticketLabel = "",
  sportsbook,
  ticketPrice,
  stakeUnits,
  legs,
}) {
  const normalizedLegs = (Array.isArray(legs) ? legs : []).filter(
    (leg) => leg?.fight_id && ["fighter_a", "fighter_b"].includes(leg.bet_side)
  );

  if (normalizedLegs.length < 2) {
    throw new Error("Select at least two moneyline legs for the parlay.");
  }
  if (!sportsbook?.trim()) {
    throw new Error("Select the sportsbook used for the parlay.");
  }
  if (!validAmericanOdds(ticketPrice)) {
    throw new Error("Enter valid combined American odds for the parlay.");
  }
  if (!(Number(stakeUnits) > 0)) {
    throw new Error("Enter a parlay stake greater than zero units.");
  }
  if (normalizedLegs.some((leg) => !validAmericanOdds(leg.leg_price))) {
    throw new Error("Enter valid American odds for every selected parlay leg.");
  }

  return persistTicket({ticket_type:"parlay",ticket_label:ticketLabel.trim(),
    bet_sportsbook:sportsbook.trim(),ticket_price:Number(ticketPrice),stake_units:Number(stakeUnits),
    request_id:crypto.randomUUID()},normalizedLegs.map(leg=>({...leg,leg_price:Number(leg.leg_price)})));
}

async function persistTicket(ticket,legs,ticketId=null,revision=null) {
  const {data,error}=await supabase.rpc("mma_save_ticket",{p_ticket:ticket,p_legs:legs,p_ticket_id:ticketId,p_revision:revision});
  if(error) throw error;
  return data;
}

async function getCompletedLeanRows() {
  const { data, error } = await supabase
    .from("fight_research")
    .select(`
      user_lean,
      fights!inner (
        fighter_a_id,
        fighter_b_id,
        winner_id,
        fight_status
      )
    `)
    .in("user_lean", ["fighter_a", "fighter_b"])
    .eq("fights.fight_status", "completed")
    .not("fights.winner_id", "is", null);

  if (error) {
    throw error;
  }

  return (data ?? []).map((row) => ({
    user_lean: row.user_lean,
    ...one(row.fights),
  }));
}

export async function getCappingDiagnostics() {
  const [bets, leanRows] = await Promise.all([
    getTrackedBets({ includeArchived: true }),
    getCompletedLeanRows(),
  ]);
  const fightIds = [...new Set(
    bets.flatMap((bet) =>
      bet.ticket_type === "parlay"
        ? (bet.legs ?? []).map((leg) => leg.fight_id)
        : [bet.fight_id]
    ).filter(Boolean)
  )];
  const oddsByFight = await getLatestMoneylinesForFights(fightIds);

  const trackedCloseMovement = buildTrackedCloseDiagnostics(bets, oddsByFight);
  const savedLeanAccuracy = summarizeLeanAccuracy(leanRows);
  return {
    tracked_close_movement: trackedCloseMovement,
    saved_lean_accuracy: savedLeanAccuracy,
    process_scorecard: buildProcessScorecard(
      bets,
      trackedCloseMovement,
      savedLeanAccuracy
    ),
  };
}
