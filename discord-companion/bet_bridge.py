"""Read accepted FightCenter bets and render snapshots without settlement data."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from uuid import UUID

from setup_discord import SetupError


FIGHT_SELECT = (
    "fight_id,event_id,"
    "fighter_a:fighters!fights_fighter_a_id_fkey(full_name),"
    "fighter_b:fighters!fights_fighter_b_id_fkey(full_name),"
    "events(event_id,event_name)"
)
SINGLE_SELECT = (
    "fight_id,owner_id,bet_side,bet_sportsbook,bet_price,stake_units,bet_archived_at,"
    "fights!inner(" + FIGHT_SELECT + ")"
)
TICKET_SELECT = (
    "ticket_id,owner_id,ticket_type,ticket_label,bet_sportsbook,ticket_price,stake_units,archived_at,"
    "bet_legs(leg_id,fight_id,bet_side,leg_price,leg_order,fights(" + FIGHT_SELECT + "))"
)


def relation(value):
    if isinstance(value, list):
        if len(value) != 1:
            raise SetupError("A saved bet has an incomplete fight link. Existing My Bets was kept.")
        value = value[0]
    if not isinstance(value, dict):
        raise SetupError("A saved bet has an incomplete fight link. Existing My Bets was kept.")
    return value


def identifier(value):
    value = str(value or "")
    if not value.isascii() or not value.isdigit() or int(value) <= 0:
        raise SetupError("A saved bet has an invalid reference. Existing My Bets was kept.")
    return str(int(value))


def bet_row(value):
    if not isinstance(value, dict):
        raise SetupError("A saved bet response is incomplete. Existing My Bets was kept.")
    return value


def owner_identifier(value):
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        raise SetupError("MMA_DASHBOARD_BET_OWNER_ID must be the dashboard user's UUID.") from None


def amount(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0:
            return None
        return format(number.normalize(), "f")
    except (InvalidOperation, ValueError, TypeError):
        return None


def moneyline(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number != number.to_integral_value() or abs(number) < 100:
            return None
        return int(number)
    except (InvalidOperation, ValueError, TypeError):
        return None


def selection(row):
    fight = relation(row.get("fights"))
    side = row.get("bet_side")
    if side not in {"fighter_a", "fighter_b"}:
        raise SetupError("A saved bet has an unknown selection. Existing My Bets was kept.")
    fighter = relation(fight.get(side))
    event = relation(fight.get("events"))
    name = str(fighter.get("full_name") or "").strip()
    if not name:
        raise SetupError("A saved bet has no confirmed fighter name. Existing My Bets was kept.")
    fid, eid = identifier(fight.get("fight_id")), identifier(fight.get("event_id"))
    if identifier(row.get("fight_id")) != fid or identifier(event.get("event_id")) != eid:
        raise SetupError("A saved bet has conflicting event references. Existing My Bets was kept.")
    return {"fight_id": fid, "event_id": eid, "selection": name,
            "event_name": str(event.get("event_name") or "Card").strip()}


def chunks(values, size=80):
    values = sorted({identifier(value) for value in values}, key=int)
    for start in range(0, len(values), size):
        yield values[start:start + size]


def fetch_bets(reader, event_ids, owner_id=None):
    """One optional snapshot for current-week cards; a partial read is not empty."""
    wanted = {identifier(eid) for eid in event_ids}
    panels = {eid: [] for eid in wanted}
    owner_id = owner_identifier(owner_id)
    if not wanted:
        return panels, owner_id
    singles, candidates = {}, set()
    for batch in chunks(wanted):
        query = [("select", SINGLE_SELECT), ("fights.event_id", "in.(" + ",".join(batch) + ")"),
                 ("bet_archived_at", "is.null"), ("stake_units", "gt.0"),
                 ("bet_side", "in.(fighter_a,fighter_b)"), ("bet_price", "not.is.null")]
        for row in reader.rows("fight_research", query):
            row = bet_row(row)
            singles[identifier(row.get("fight_id"))] = row
        for row in reader.rows("bet_legs", [("select", "ticket_id,fights!inner(event_id)"),
                              ("fights.event_id", "in.(" + ",".join(batch) + ")")]):
            row = bet_row(row)
            if identifier(relation(row.get("fights")).get("event_id")) in wanted:
                candidates.add(identifier(row.get("ticket_id")))
    tickets = {}
    for batch in chunks(candidates):
        query = [("select", TICKET_SELECT), ("ticket_id", "in.(" + ",".join(batch) + ")"),
                 ("ticket_type", "eq.parlay"), ("archived_at", "is.null"), ("stake_units", "gt.0")]
        if owner_id:
            query.append(("owner_id", "eq." + owner_id))
        for row in reader.rows("bet_tickets", query):
            row = bet_row(row)
            if row.get("archived_at") or row.get("ticket_type") != "parlay" or not amount(row.get("stake_units")):
                continue
            current_owner = owner_identifier(row.get("owner_id"))
            if not current_owner:
                raise SetupError("A parlay has no dashboard owner. Existing My Bets was kept.")
            if owner_id and current_owner != owner_id:
                continue
            tickets[identifier(row.get("ticket_id"))] = row
    owners = {owner_identifier(row["owner_id"]) for row in tickets.values()}
    for row in singles.values():
        if (not row.get("bet_archived_at") and amount(row.get("stake_units"))
                and moneyline(row.get("bet_price")) is not None and row.get("bet_side") in {"fighter_a", "fighter_b"}):
            row_owner = owner_identifier(row.get("owner_id"))
            if row_owner and (not owner_id or row_owner == owner_id):
                owners.add(row_owner)
    if len(owners) > 1:
        raise SetupError("Saved bets have multiple dashboard owners. Set MMA_DASHBOARD_BET_OWNER_ID in the bot's .env; existing My Bets was kept.")
    owner_id = owner_id or next(iter(owners), None)
    for fid, row in singles.items():
        stake, price = amount(row.get("stake_units")), moneyline(row.get("bet_price"))
        if row.get("bet_archived_at") or not stake or price is None or row.get("bet_side") not in {"fighter_a", "fighter_b"}:
            continue
        # Legacy singles are shared research rows in the personal dashboard.
        # A non-null owner must still match a bound/configured ticket owner.
        row_owner = owner_identifier(row.get("owner_id"))
        if owner_id and row_owner and row_owner != owner_id:
            continue
        detail = selection(row)
        if detail["event_id"] in wanted:
            panels[detail["event_id"]].append({"bet_id": "single:" + fid, "type": "single",
                "stake": stake, "price": price, "sportsbook": str(row.get("bet_sportsbook") or "Book not recorded").strip(),
                "selection": detail["selection"], "fight_id": fid})
    for tid, row in tickets.items():
        price = moneyline(row.get("ticket_price"))
        if price is None:
            raise SetupError("A recorded parlay has no valid accepted price. Existing My Bets was kept.")
        legs = row.get("bet_legs")
        if not isinstance(legs, list) or len(legs) < 2:
            raise SetupError("A recorded parlay has incomplete legs. Existing My Bets was kept.")
        ordered = []
        for leg in legs:
            leg = bet_row(leg)
            detail = selection(leg)
            leg_price = moneyline(leg.get("leg_price"))
            if leg_price is None:
                raise SetupError("A recorded parlay leg has no accepted price. Existing My Bets was kept.")
            detail.update(price=leg_price, order=int(identifier(leg.get("leg_order"))))
            ordered.append(detail)
        ordered.sort(key=lambda leg: (leg["order"], int(leg["fight_id"])))
        if len({leg["fight_id"] for leg in ordered}) != len(ordered) or len({leg["order"] for leg in ordered}) != len(ordered):
            raise SetupError("A recorded parlay has conflicting legs. Existing My Bets was kept.")
        ticket = {"bet_id": "parlay:" + tid, "type": "parlay", "stake": amount(row["stake_units"]),
                  "price": price, "sportsbook": str(row.get("bet_sportsbook") or "Book not recorded").strip(),
                  "label": str(row.get("ticket_label") or "").strip(), "legs": ordered}
        for eid in wanted.intersection(leg["event_id"] for leg in ordered):
            panels[eid].append(ticket)
    for records in panels.values():
        records.sort(key=lambda record: (record["type"] != "single", int(record["bet_id"].split(":")[1])))
    return panels, owner_id


def bet_payloads(records):
    # Imported at call time so the publisher can import this module safely.
    from sync_discord import embed_pages, split_text, units
    if not records:
        return [{"content": "", "embeds": [{"title": "🎟️ My Bets", "color": 0x57A88C,
                 "description": "No recorded bets for this card.\nSaved FightCenter bets appear with the next research sync.",
                 "footer": {"text": "FightCenter • Accepted bets"}}]}]
    fields = []
    counts = {"single": 0, "parlay": 0}
    for record in records:
        kind = record["type"]
        counts[kind] += 1
        name = ("🎯 Single " if kind == "single" else "🎟️ Parlay ") + str(counts[kind])
        line = f"**{record['stake']}u • {record['price']:+d} • {record['sportsbook']}**"
        if kind == "single":
            text = record["selection"] + "\n" + line
        else:
            text = ((record["label"] + "\n") if record["label"] else "") + line
            cross_card = len({leg["event_id"] for leg in record["legs"]}) > 1
            if cross_card:
                text += "\n**Across cards — one shared ticket**"
            for index, leg in enumerate(record["legs"], 1):
                text += f"\n{index}. {leg['selection']} ({leg['price']:+d})"
                if cross_card:
                    text += " • " + leg["event_name"]
        # Keep each normal leg on one field line. Only an individually long
        # line needs the generic UTF-16 splitter.
        pieces, current = [], ""
        for line in text.splitlines():
            for part in split_text(line, 950) if line else [""]:
                candidate = current + ("\n" if current else "") + part
                if current and units(candidate) > 950:
                    pieces.append(current)
                    current = part
                else:
                    current = candidate
        if current:
            pieces.append(current)
        fields.extend({"name": name + (f" • continued {i + 1}/{len(pieces)}" if len(pieces) > 1 else ""),
                       "value": piece.strip()} for i, piece in enumerate(pieces))
    pages = embed_pages("🎟️ My Bets", "Recorded in FightCenter • Singles and complete parlay tickets", fields,
                        footer="FightCenter • Accepted bets", per_page=25)
    for page in pages:
        for embed in page["embeds"]:
            embed["color"] = 0x57A88C
    embeds = [embed for page in pages for embed in page["embeds"]]
    size = sum(units(embed.get("title", "")) + units(embed.get("description", ""))
               + units(embed["footer"]["text"])
               + sum(units(field["name"]) + units(field["value"]) for field in embed.get("fields", []))
               for embed in embeds)
    return [{"content": "", "embeds": embeds}] if len(embeds) <= 10 and size <= 5400 else pages
