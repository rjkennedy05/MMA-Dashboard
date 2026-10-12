"""Cross-check PFL's declared card against its official live/result response."""

from datetime import date, datetime
import json
import re
import unicodedata
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


class OfficialPflCardError(ValueError):
    pass


def name_key(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", value.lower())


def trusted_event_url(value):
    parsed = urlparse(str(value or ""))
    if (parsed.scheme != "https" or parsed.hostname not in {"pflmma.com", "www.pflmma.com"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or not re.fullmatch(r"/event/[a-zA-Z0-9_-]+/?", parsed.path)
            or parsed.query):
        raise OfficialPflCardError("The PFL card URL is not an official event URL.")
    return parsed._replace(fragment="").geturl().rstrip("/")


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def card_metadata(html, entry):
    url = trusted_event_url(entry["external_url"])
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.get_text())
        except (ValueError, TypeError):
            continue
        for row in _walk(payload):
            if (row.get("@type") == "SportsEvent"
                    and str(row.get("@id", "")).rstrip("/") == url + "#event"):
                matches.append(row)
    if len(matches) != 1:
        raise OfficialPflCardError("PFL did not declare one identifiable event card.")
    metadata = matches[0]
    try:
        declared = date.fromisoformat(str(metadata.get("startDate", ""))[:10])
        expected = date.fromisoformat(str(entry["date"])[:10])
    except ValueError as error:
        raise OfficialPflCardError("The PFL card did not declare a usable event date.") from error
    if declared != expected:
        raise OfficialPflCardError("The official PFL card date differs from its catalog entry.")
    if not metadata.get("subEvent"):
        raise OfficialPflCardError("PFL has not declared the complete matchup list.")
    return metadata


def _declared_pairs(metadata):
    pairs = {}
    for row in metadata["subEvent"]:
        fighters = row.get("competitor") or []
        names = [name_key(f.get("name")) for f in fighters]
        if len(names) != 2 or not all(names) or names[0] == names[1]:
            raise OfficialPflCardError("The declared PFL card has an incomplete matchup.")
        pair = tuple(sorted(names))
        if pair in pairs:
            raise OfficialPflCardError("PFL declared a duplicate matchup.")
        pairs[pair] = {name_key(f["name"]): f.get("url") for f in fighters}
    return pairs


def _identity(value, label):
    value = str(value or "")
    if not re.fullmatch(r"[1-9]\d*", value):
        raise OfficialPflCardError(f"The PFL {label} identity is missing or invalid.")
    return value


def _status(row, fighter_ids):
    raw = str(row.get("Status") or "").strip().lower()
    override = str(row.get("OverrideStatus") or "").lower().replace(" ", "_")
    outcome = str(row.get("WinnerResult") or "").lower().replace(" ", "")
    winner = str(row.get("WinnerId")) if row.get("WinnerId") is not None else None
    if override in {"no_contest", "nocontest", "draw", "cancelled", "canceled"}:
        if winner is not None:
            raise OfficialPflCardError("PFL supplied a winner for a non-winning outcome.")
        return {"nocontest": "no_contest", "canceled": "cancelled"}.get(override, override), None
    if override:
        raise OfficialPflCardError("PFL supplied an unrecognized outcome override.")
    if raw in {"finished", "final", "completed"}:
        if outcome in {"nocontest", "draw"}:
            if winner is not None:
                raise OfficialPflCardError("PFL supplied conflicting final-result fields.")
            return ("no_contest" if outcome == "nocontest" else "draw"), None
        if winner not in fighter_ids or outcome not in {"red", "blue"}:
            raise OfficialPflCardError("PFL has not supplied a verified winner for a finished fight.")
        return "completed", winner
    if winner is not None:
        raise OfficialPflCardError("PFL supplied a winner before a fight was final.")
    if raw in {"scheduled", "upcoming", "not started", "notstarted", "pending"}:
        return "scheduled", None
    if raw in {"live", "in progress", "in_progress", "started"}:
        return "in_progress", None
    if raw in {"cancelled", "canceled"}:
        return "cancelled", None
    raise OfficialPflCardError("PFL supplied an unrecognized fight status.")


def normalize_card(entry, metadata, payload):
    if not isinstance(payload, list) or not 0 < len(payload) <= 100:
        raise OfficialPflCardError("The official PFL fight response was empty or unrecognized.")
    declared = _declared_pairs(metadata)
    url = trusted_event_url(entry["external_url"])
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    fights, seen_pairs, seen_ids, seen_orders = [], set(), set(), set()
    states = []
    for row in payload:
        fight_id = _identity(row.get("FightId"), "fight")
        order = int(row.get("FightNumber") or 0)
        if order < 1 or order in seen_orders or fight_id in seen_ids:
            raise OfficialPflCardError("PFL supplied a duplicate identity or invalid card order.")
        raw_fighters = row.get("Fighters") or []
        if len(raw_fighters) != 2:
            raise OfficialPflCardError("The PFL fight response has an incomplete matchup.")
        ids = [_identity(f.get("Id"), "fighter") for f in raw_fighters]
        names = [" ".join((str(f.get("FirstName") or "") + " " + str(f.get("LastName") or "")).split())
                 for f in raw_fighters]
        pair = tuple(sorted(name_key(name) for name in names))
        if len(set(ids)) != 2 or pair not in declared or pair in seen_pairs:
            raise OfficialPflCardError("PFL's result response disagrees with its declared matchup list.")
        state, winner = _status(row, ids)
        corners = [str(f.get("Corner") or "").lower() for f in raw_fighters]
        if set(corners) != {"red", "blue"} or len(set(corners)) != 2:
            raise OfficialPflCardError("PFL did not declare two distinct fighter corners.")
        if winner and corners[ids.index(winner)] != str(row.get("WinnerResult")).lower():
            raise OfficialPflCardError("PFL's winner identity and corner disagree.")
        slots = []
        for index, (fighter_id, fighter_name) in enumerate(zip(ids, names), 1):
            slots.append({"order": index, "winner": fighter_id == winner,
                "athlete": {"id": "pfl-fighter:" + fighter_id, "displayName": fighter_name,
                            "link": {"href": declared[pair][name_key(fighter_name)]}}})
        status = {"type": {"name": state, "state": "post" if state in
                    {"completed", "no_contest", "draw", "cancelled"} else "in" if state == "in_progress" else "pre",
                    "completed": state in {"completed", "no_contest", "draw"}},
                  "result": {"displayName": str(row.get("WinBy") or "").strip() or None}}
        clock = str(row.get("RoundTime") or "").strip()
        if clock:
            match = re.fullmatch(r"R([1-5]),?\s+(\d{1,2}):([0-5]\d)", clock, re.I)
            if not match or int(match[2]) > 5 or (int(match[2]) == 5 and int(match[3])):
                raise OfficialPflCardError("PFL supplied an invalid finish round/time.")
            status.update(period=int(match[1]), clock=int(match[2]) * 60 + int(match[3]))
        method = status["result"]["displayName"]
        if state == "completed" and not method:
            raise OfficialPflCardError("PFL supplied a final winner without a result method.")
        rounds = row.get("MaxRounds") or (5 if status.get("period", 0) > 3 else 3)
        fights.append({"id": f"pfl-fight:{slug}:{fight_id}", "official_order": order,
            "competitors": slots, "status": status, "type": {"text": row.get("WeightClass")},
            "format": {"regulation": {"periods": rounds}}, "external_url": url})
        seen_ids.add(fight_id)
        seen_orders.add(order)
        seen_pairs.add(pair)
        states.append(state)
    if seen_pairs != set(declared):
        raise OfficialPflCardError("PFL's response omitted part of the declared card; existing data was kept.")
    location = metadata.get("location") or {}
    address = location.get("address") or {}
    event = {"external_id": entry["external_id"], "name": entry["name"],
             "event_date": str(entry["date"])[:10], "external_url": url,
             "event_status": "cancelled" if all(s == "cancelled" for s in states) else "completed" if all(s in {"completed", "draw", "no_contest", "cancelled"}
                 for s in states) else "live" if "in_progress" in states else "upcoming",
             "city": address.get("addressLocality"), "country": address.get("addressCountry")}
    if location.get("name") != address.get("addressLocality"):
        event["venue"] = location.get("name")
    # The PFL site often uses midnight as a date placeholder, not a start time.
    instant = datetime.fromisoformat(str(metadata["startDate"]).replace("Z", "+00:00"))
    if instant.tzinfo and (instant.hour, instant.minute, instant.second) != (0, 0, 0):
        if instant.astimezone(ZoneInfo("America/Chicago")).date().isoformat() != event["event_date"]:
            raise OfficialPflCardError("PFL's start time conflicts with the catalog's Central Time date.")
        event["event_start_time"] = instant.isoformat()
    return event, sorted(fights, key=lambda fight: fight["official_order"])
