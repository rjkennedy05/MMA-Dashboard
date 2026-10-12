from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo


DASHBOARD_TIMEZONE = ZoneInfo("America/Chicago")
PLACEHOLDER_FIGHTER_NAMES = {
    "opponent tba",
    "tba",
    "tbd",
    "to be announced",
    "to be determined",
}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _as_datetime(value: Any) -> datetime:
    text = _text(value)
    if not text:
        raise ValueError("ESPN row is missing its date.")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        elif value not in (None, "", [], {}):
            result[key] = value
    return result


def event_external_id(event: dict[str, Any]) -> str:
    value = event.get("id")
    if value is None:
        value = _object(event.get("event")).get("id")
    if value is None:
        raise ValueError("ESPN MMA event is missing its id.")
    return str(value)


def event_name(event: dict[str, Any]) -> str:
    value = _text(event.get("name"))
    if not value and isinstance(event.get("event"), dict):
        value = _text(event["event"].get("name"))
    if not value:
        raise ValueError(
            f"ESPN MMA event {event_external_id(event)} has no name."
        )
    return value


def event_promotion_key(event: dict[str, Any]) -> str:
    name = event_name(event).casefold().replace("’", "'")
    if "contender series" in name:
        return "dwcs"
    return "ufc"


def event_datetime(event: dict[str, Any]) -> datetime:
    value = event.get("date")
    if not value and isinstance(event.get("event"), dict):
        value = event["event"].get("date")
    return _as_datetime(value)


def dashboard_event_date(event: dict[str, Any]) -> date:
    return event_datetime(event).astimezone(DASHBOARD_TIMEZONE).date()


def event_in_window(
    event: dict[str, Any],
    start: date,
    end: date,
) -> bool:
    current = dashboard_event_date(event)
    return start <= current <= end


def _fightcenter_competitions(
    fightcenter: dict[str, Any],
) -> Iterable[dict[str, Any]]:
    cards = fightcenter.get("cards") or {}
    if not isinstance(cards, dict):
        return
    for card in cards.values():
        if not isinstance(card, dict):
            continue
        for fight in card.get("competitions") or []:
            if isinstance(fight, dict):
                yield fight


def _normalized_identity_text(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())


def _athlete_external_id(slot: dict[str, Any]) -> str | None:
    athlete = _object(slot.get("athlete"))
    value = athlete.get("id")
    if value is None:
        ref = str(athlete.get("$ref") or "")
        match = re.search(r"/athletes/(\d+)", ref)
        value = match.group(1) if match else None
    if value is None:
        value = slot.get("id")
    return str(value) if value is not None else None


def fight_matchup_identity(fight: dict[str, Any]) -> tuple[str, str] | None:
    names: list[str] = []
    athlete_ids: list[str] = []
    for slot in _competitor_slots(fight):
        athlete = _object(slot.get("athlete"))
        athlete_id = _athlete_external_id(slot)
        name = _text(
            athlete.get("displayName")
            or athlete.get("fullName")
            or slot.get("displayName")
        )
        if name:
            names.append(_normalized_identity_text(name))
        if athlete_id:
            athlete_ids.append(str(athlete_id))

    # Names are the common identity available in both ESPN payloads. One feed
    # can expose stable athlete IDs while another exposes competition-slot IDs,
    # which is the provider mismatch that originally duplicated card rows.
    if len(names) == 2 and all(names):
        return tuple(sorted(f"name:{name}" for name in names))
    if len(athlete_ids) == 2:
        return tuple(sorted(f"id:{athlete_id}" for athlete_id in athlete_ids))
    return None


def _fight_detail_score(fight: dict[str, Any]) -> int:
    score = 0
    slots = _competitor_slots(fight)
    if len(slots) == 2:
        score += 10
    score += sum(
        3
        for slot in slots
        if isinstance(slot.get("athlete"), dict)
        and (
            slot["athlete"].get("displayName")
            or slot["athlete"].get("fullName")
        )
    )
    score += 4 if isinstance(fight.get("status"), dict) else 0
    score += 2 if fight.get("matchNumber") is not None else 0
    score += 2 if fight.get("type") else 0
    score += 2 if fight.get("format") else 0
    return score


def event_fights(
    event: dict[str, Any],
    fightcenter: dict[str, Any],
) -> list[dict[str, Any]]:
    scoreboard_fights = {
        str(fight["id"]): fight
        for fight in event.get("competitions") or []
        if isinstance(fight, dict) and fight.get("id") is not None
    }
    detailed_fights = {
        str(fight["id"]): fight
        for fight in _fightcenter_competitions(fightcenter)
        if fight.get("id") is not None
    }
    fight_ids = sorted(
        set(scoreboard_fights) | set(detailed_fights),
        key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else value),
    )
    merged_fights = [
        deep_merge(
            scoreboard_fights.get(fight_id, {}),
            detailed_fights.get(fight_id, {}),
        )
        for fight_id in fight_ids
    ]

    # ESPN occasionally publishes one matchup under different competition IDs
    # in its scoreboard and FightCenter payloads. Merge those rows by the two
    # athlete identities so one provider quirk cannot create a duplicate bout.
    fights_by_matchup: dict[tuple[str, str], dict[str, Any]] = {}
    unmatched: list[dict[str, Any]] = []
    for fight in merged_fights:
        identity = fight_matchup_identity(fight)
        if identity is None:
            unmatched.append(fight)
            continue
        existing = fights_by_matchup.get(identity)
        if existing is None:
            fights_by_matchup[identity] = fight
            continue
        if _fight_detail_score(fight) >= _fight_detail_score(existing):
            fights_by_matchup[identity] = deep_merge(existing, fight)
        else:
            fights_by_matchup[identity] = deep_merge(fight, existing)

    fights = [*fights_by_matchup.values(), *unmatched]
    fights.sort(
        key=lambda fight: (
            int(fight.get("matchNumber") or 999),
            fight_external_id(fight),
        )
    )
    return fights


def fight_external_id(fight: dict[str, Any]) -> str:
    value = fight.get("id")
    if value is None:
        raise ValueError("ESPN MMA fight is missing its id.")
    return str(value)


def _competitor_slots(fight: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        row
        for row in fight.get("competitors") or []
        if isinstance(row, dict)
    ]
    rows.sort(key=lambda row: int(row.get("order") or 99))
    return rows[:2]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _display_inches(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    feet_match = re.search(r"(\d+)\s*'\s*(\d+)", text)
    if feet_match:
        return int(feet_match.group(1)) * 12 + int(feet_match.group(2))
    inches_match = re.search(r"(\d+(?:\.\d+)?)", text)
    return round(float(inches_match.group(1))) if inches_match else None


def _profile_value(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("name") or value.get("alt"))
    return _text(value)


def _image_url(value: Any) -> str | None:
    if isinstance(value, dict):
        return _text(value.get("href") or value.get("url"))
    text = _text(value)
    return text if text and text.startswith(("http://", "https://")) else None


def fighter_profile(slot: dict[str, Any]) -> dict[str, Any]:
    """Return only current provider facts that map to dashboard columns."""
    athlete = _object(slot.get("athlete"))
    height = _number(athlete.get("height"))
    reach = _number(athlete.get("reach"))
    stance = _profile_value(athlete.get("stance"))
    if stance in {"--", "-"}:
        stance = None

    nationality = _text(
        athlete.get("citizenship")
        or athlete.get("country")
        or _profile_value(athlete.get("flag"))
    )
    if nationality in {"--", "-"}:
        nationality = None

    record = _text(slot.get("displayRecord"))
    if record in {"--", "-", "0-0-0"}:
        record = None

    age = _number(athlete.get("age"))
    date_of_birth = _text(athlete.get("dateOfBirth"))
    if date_of_birth:
        date_match = re.match(r"\d{4}-\d{2}-\d{2}", date_of_birth)
        date_of_birth = date_match.group(0) if date_match else None
    return {
        "nickname": _text(athlete.get("nickname")),
        "date_of_birth": date_of_birth,
        "height_inches": (
            round(height)
            if height is not None
            else _display_inches(athlete.get("displayHeight"))
        ),
        "reach_inches": (
            round(reach)
            if reach is not None
            else _display_inches(athlete.get("displayReach"))
        ),
        "stance": stance,
        "nationality": nationality,
        "record_summary": record,
        "age_snapshot": round(age) if age is not None else None,
        "image_url": _image_url(
            athlete.get("headshot")
            or athlete.get("image")
            or athlete.get("photo")
        ),
    }


def fighters(fight: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    slots = _competitor_slots(fight)
    if len(slots) != 2:
        raise ValueError(
            f"ESPN MMA fight {fight_external_id(fight)} does not have two fighters."
        )

    normalized = []
    for slot in slots:
        athlete = _object(slot.get("athlete"))
        fighter_id = _athlete_external_id(slot)
        name = _text(
            athlete.get("displayName")
            or athlete.get("fullName")
            or slot.get("displayName")
        )
        if fighter_id is None or not name:
            raise ValueError(
                f"ESPN MMA fight {fight_external_id(fight)} has an incomplete fighter."
            )
        link = _object(athlete.get("link"))
        normalized.append(
            {
                "external_id": str(fighter_id),
                "name": name,
                "winner": slot.get("winner") is True,
                "external_url": _text(link.get("href")),
                "profile": fighter_profile(slot),
            }
        )
    return normalized[0], normalized[1]


def is_placeholder_fight(fight: dict[str, Any]) -> bool:
    """Incomplete provider placeholders are not stable fighter identities."""
    try:
        matchup = fighters(fight)
    except ValueError:
        return True

    return any(
        " ".join(fighter["name"].casefold().split())
        in PLACEHOLDER_FIGHTER_NAMES
        for fighter in matchup
    )


def matchup_label(fight: dict[str, Any]) -> str:
    """Return a safe display label even for incomplete provider placeholders."""
    try:
        matchup = fighters(fight)
    except ValueError:
        return "Unknown matchup"

    return " vs ".join(
        fighter.get("name") or "Unknown"
        for fighter in matchup
    )


def weight_class(fight: dict[str, Any]) -> str | None:
    raw = fight.get("type") or {}
    if isinstance(raw, dict):
        name = _text(raw.get("text") or raw.get("abbreviation"))
    else:
        name = _text(raw)

    if not name:
        for row in fight.get("types") or []:
            if isinstance(row, dict):
                name = _text(row.get("text"))
                if name:
                    name = name.removesuffix(" Title").strip()
                    break

    genders = {
        str(_object(slot.get("athlete")).get("gender") or "").upper()
        for slot in _competitor_slots(fight)
    }
    if (
        name
        and genders == {"FEMALE"}
        and not name.casefold().startswith(("women", "w "))
    ):
        name = f"Women's {name}"
    return name


def scheduled_rounds(fight: dict[str, Any]) -> int:
    fight_format = _object(fight.get("format"))
    regulation = _object(fight_format.get("regulation"))
    value = regulation.get("periods")
    try:
        rounds = int(value)
    except (TypeError, ValueError):
        rounds = 5 if is_title_fight(fight) else 3
    return rounds if rounds in (1, 2, 3, 4, 5) else 3


def _status(fight: dict[str, Any]) -> dict[str, Any]:
    status = fight.get("status")
    return status if isinstance(status, dict) else {}


def _result(fight: dict[str, Any]) -> dict[str, Any]:
    result = _status(fight).get("result")
    return result if isinstance(result, dict) else {}


def normalized_status(fight: dict[str, Any]) -> str:
    status = _status(fight)
    status_type = _object(status.get("type"))
    values = " ".join(
        str(value).casefold()
        for value in (
            status_type.get("name"),
            status_type.get("state"),
            status_type.get("description"),
            status_type.get("detail"),
            _result(fight).get("displayName"),
        )
        if value is not None
    )
    if "no contest" in values or "no_contest" in values:
        return "no_contest"
    if "draw" in values:
        return "draw"
    if status_type.get("completed") is True or "final" in values:
        return "completed"
    if any(token in values for token in ("cancel", "postpon", "abandon")):
        return "cancelled"
    if status_type.get("state") == "in" or "progress" in values:
        return "in_progress"
    return "scheduled"


def winner_external_id(fight: dict[str, Any]) -> str | None:
    try:
        for fighter in fighters(fight):
            if fighter["winner"]:
                return fighter["external_id"]
    except ValueError:
        return None
    return None


def finish_method(fight: dict[str, Any]) -> str | None:
    result = _result(fight)
    display = _text(
        result.get("displayName")
        or result.get("shortDisplayName")
        or result.get("name")
    )
    description = _text(
        result.get("displayDescription") or result.get("description")
    )
    if display and description and description.casefold() not in display.casefold():
        return f"{display} ({description})"
    return display


def finish_round(fight: dict[str, Any]) -> int | None:
    if normalized_status(fight) not in {"completed", "draw", "no_contest"}:
        return None
    try:
        return int(_status(fight).get("period"))
    except (TypeError, ValueError):
        return None


def finish_time_seconds(fight: dict[str, Any]) -> int | None:
    if normalized_status(fight) not in {"completed", "draw", "no_contest"}:
        return None
    value = _status(fight).get("clock")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def result_type(fight: dict[str, Any]) -> str | None:
    status = normalized_status(fight)
    if status == "draw":
        return "draw"
    if status == "no_contest":
        return "no_contest"
    if status == "completed":
        return "win"
    return None


def is_title_fight(fight: dict[str, Any]) -> bool:
    values = [_text(fight.get("note")) or ""]
    for row in fight.get("types") or []:
        if isinstance(row, dict):
            values.append(_text(row.get("text")) or "")
    return any("title" in value.casefold() for value in values)


def event_status(event: dict[str, Any]) -> str:
    status = _object(event.get("status"))
    status_type = _object(status.get("type"))
    state = str(status_type.get("state") or "").casefold()
    if status_type.get("completed") is True or state == "post":
        return "completed"
    if state == "in":
        return "live"
    return "upcoming"


def event_location(event: dict[str, Any]) -> dict[str, str | None]:
    competition = next(
        (
            row
            for row in event.get("competitions") or []
            if isinstance(row, dict)
        ),
        {},
    )
    venue = _object(competition.get("venue"))
    address = _object(venue.get("address"))
    return {
        "venue": _text(venue.get("fullName")),
        "city": _text(address.get("city")),
        "state_region": _text(address.get("state")),
        "country": _text(address.get("country")),
    }


def watch_platform(event: dict[str, Any]) -> str | None:
    names: list[str] = []
    for competition in event.get("competitions") or []:
        if not isinstance(competition, dict):
            continue
        for broadcast in competition.get("broadcasts") or []:
            if not isinstance(broadcast, dict):
                continue
            for name in broadcast.get("names") or []:
                text = _text(name)
                if text and text not in names:
                    names.append(text)
    return " / ".join(names) if names else None


def event_external_url(event: dict[str, Any]) -> str | None:
    for link in event.get("links") or []:
        if isinstance(link, dict) and "summary" in (link.get("rel") or []):
            return _text(link.get("href"))
    return None
