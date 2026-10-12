from __future__ import annotations

import html as html_module
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag


DASHBOARD_TIMEZONE = ZoneInfo("America/Chicago")
LFA_NUMBER_PATTERN = re.compile(r"\bLFA\s*[-#:]?\s*(\d+)\b", re.I)
SHERDOG_EVENT_ID_PATTERN = re.compile(r"-(\d+)(?:/)?$")
SHERDOG_FIGHTER_ID_PATTERN = re.compile(r"-(\d+)(?:/)?$")
TIME_PATTERN = re.compile(r"^(\d+):(\d{2})$")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = html_module.unescape(str(value)).strip()
    return re.sub(r"\s+", " ", result) or None


def _node_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    return _text(node.get_text(" ", strip=True))


def _event_number(value: str | None) -> int | None:
    match = LFA_NUMBER_PATTERN.search(value or "")
    return int(match.group(1)) if match else None


def _event_external_id(value: str | None) -> str | None:
    number = _event_number(value)
    return f"lfa-{number}" if number is not None else None


def _as_datetime(value: Any) -> datetime:
    text = _text(value)
    if not text:
        raise ValueError("LFA event is missing its date.")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _official_schema_rows(html: str) -> Iterable[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for row in candidates:
            if not isinstance(row, dict):
                continue
            schema_type = row.get("@type")
            if schema_type == "Event" or (
                isinstance(schema_type, list) and "Event" in schema_type
            ):
                yield row


def _official_location(row: dict[str, Any]) -> dict[str, str | None]:
    location = row.get("location")
    if not isinstance(location, dict):
        return {
            "venue": None,
            "city": None,
            "state_region": None,
            "country": None,
        }
    address = location.get("address")
    if not isinstance(address, dict):
        address = {}
    return {
        "venue": _text(location.get("name")),
        "city": _text(address.get("addressLocality")),
        "state_region": _text(address.get("addressRegion")),
        "country": _text(address.get("addressCountry")),
    }


def _watch_platform(description: str | None) -> str:
    value = (description or "").casefold()
    platforms: list[str] = []
    for needle, label in (
        ("vice tv", "VICE TV"),
        ("espn deportes", "ESPN Deportes"),
        ("espn knockout", "ESPN KnockOut"),
        ("ufc fight pass", "UFC Fight Pass"),
    ):
        if needle in value and label not in platforms:
            platforms.append(label)
    return " / ".join(platforms) if platforms else "LFA"


def parse_official_events(
    html: str,
    status: str,
) -> list[dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for row in _official_schema_rows(html):
        name = _text(row.get("name"))
        url = _text(row.get("url"))
        external_id = _event_external_id(name or url)
        start_date = _text(row.get("startDate"))
        if not name or not url or not external_id or not start_date:
            continue
        description = _text(row.get("description"))
        events[external_id] = {
            "external_id": external_id,
            "name": name.replace(" - ", ": ", 1),
            "date": _as_datetime(start_date),
            "external_url": url,
            "sherdog_url": None,
            "status": status,
            "watch_platform": _watch_platform(description),
            **_official_location(row),
        }
    return list(events.values())


def _split_sherdog_location(value: str | None) -> dict[str, str | None]:
    parts = [part.strip() for part in (value or "").split(",") if part.strip()]
    if not parts:
        return {
            "venue": None,
            "city": None,
            "state_region": None,
            "country": None,
        }
    country = parts[-1] if len(parts) >= 3 else None
    state_region = parts[-2] if len(parts) >= 4 else None
    city = parts[-3] if len(parts) >= 4 else (
        parts[-2] if len(parts) >= 3 else None
    )
    venue_end = -3 if len(parts) >= 4 else -2 if len(parts) >= 3 else 1
    venue_parts = parts[:venue_end]
    return {
        "venue": ", ".join(venue_parts) if venue_parts else parts[0],
        "city": city,
        "state_region": state_region,
        "country": country,
    }


def parse_sherdog_index(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    events: dict[str, dict[str, Any]] = {}
    for tab_id, status in (
        ("upcoming_tab", "upcoming"),
        ("recent_tab", "completed"),
    ):
        tab = soup.select_one(f"#{tab_id}")
        if not isinstance(tab, Tag):
            continue
        for row in tab.select('tr[itemscope][itemtype$="/Event"]'):
            link = row.select_one('a[itemprop="url"][href]')
            date_node = row.select_one('meta[itemprop="startDate"][content]')
            if not isinstance(link, Tag) or not isinstance(date_node, Tag):
                continue
            name = _node_text(link.select_one('[itemprop="name"]')) or _node_text(link)
            url = _text(link.get("href"))
            external_id = _event_external_id(name or url)
            date_value = _text(date_node.get("content"))
            if not name or not url or not external_id or not date_value:
                continue
            location_node = row.select_one('[itemprop="location"]')
            events[external_id] = {
                "external_id": external_id,
                "name": name.replace(" - ", ": ", 1),
                "date": _as_datetime(date_value),
                "external_url": None,
                "sherdog_url": url,
                "status": status,
                "watch_platform": None,
                **_split_sherdog_location(_node_text(location_node)),
            }
    if not events:
        raise ValueError("Sherdog LFA index contains no recognizable events.")
    return list(events.values())


def merge_event_listings(
    official_events: Iterable[dict[str, Any]],
    sherdog_events: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for event in official_events:
        merged[event_external_id(event)] = dict(event)
    for event in sherdog_events:
        external_id = event_external_id(event)
        existing = merged.get(external_id)
        if existing is None:
            merged[external_id] = dict(event)
            continue
        existing["sherdog_url"] = event.get("sherdog_url")
        if "to be announced" in event_name(existing).casefold():
            existing["name"] = event.get("name") or existing["name"]
        if existing.get("status") != "completed":
            existing["status"] = event.get("status") or existing["status"]
        for field in ("venue", "city", "state_region", "country"):
            if not existing.get(field):
                existing[field] = event.get(field)
    return list(merged.values())


def event_external_id(event: dict[str, Any]) -> str:
    value = _text(event.get("external_id"))
    if not value:
        raise ValueError("LFA event is missing its id.")
    return value


def event_name(event: dict[str, Any]) -> str:
    value = _text(event.get("name"))
    if not value:
        raise ValueError(f"LFA event {event_external_id(event)} has no name.")
    return value


def event_datetime(event: dict[str, Any]) -> datetime:
    value = event.get("date")
    if not isinstance(value, datetime):
        raise ValueError(f"LFA event {event_external_id(event)} has no date.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dashboard_event_date(event: dict[str, Any]) -> date:
    # Official LFA calendar entries are all-day values. Preserve their stated
    # calendar date instead of shifting midnight through another time zone.
    value = event.get("date")
    if isinstance(value, datetime):
        return value.date()
    return event_datetime(event).astimezone(DASHBOARD_TIMEZONE).date()


def event_in_window(event: dict[str, Any], start: date, end: date) -> bool:
    current = dashboard_event_date(event)
    return start <= current <= end


def event_status(event: dict[str, Any]) -> str:
    value = _text(event.get("status"))
    return value if value in {"upcoming", "live", "completed"} else "upcoming"


def event_location(event: dict[str, Any]) -> dict[str, str | None]:
    return {
        key: _text(event.get(key))
        for key in ("venue", "city", "state_region", "country")
    }


def event_external_url(event: dict[str, Any]) -> str | None:
    return _text(event.get("external_url") or event.get("sherdog_url"))


def watch_platform(event: dict[str, Any]) -> str | None:
    return _text(event.get("watch_platform"))


def sherdog_event_url(event: dict[str, Any]) -> str | None:
    return _text(event.get("sherdog_url"))


def _fighter_from_performer(node: Tag) -> dict[str, Any] | None:
    link = node.select_one('a[itemprop="url"][href]') or node.select_one('a[href*="/fighter/"]')
    if not isinstance(link, Tag):
        return None
    href = _text(link.get("href"))
    match = SHERDOG_FIGHTER_ID_PATTERN.search(urlparse(href or "").path)
    name_node = node.select_one('[itemprop="name"]')
    name = _node_text(name_node)
    if not name:
        image = node.select_one("img[alt]")
        name = _text(image.get("alt")) if isinstance(image, Tag) else None
    if not match or not name:
        return None
    external_url = (
        f"https://www.sherdog.com{href}"
        if href and href.startswith("/")
        else href
    )
    result = node.select_one(".final_result")
    outcome = " ".join(result.get("class") or []) if isinstance(result, Tag) else ""
    outcome += " " + (_node_text(result) or "")
    return {
        "external_id": match.group(1),
        "name": name,
        "winner": "win" in outcome.casefold(),
        "outcome": outcome.casefold(),
        "external_url": external_url,
    }


def _time_seconds(value: str | None) -> int | None:
    match = TIME_PATTERN.match(value or "")
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _resume_value(table: Tag | None, label: str) -> str | None:
    if not isinstance(table, Tag):
        return None
    for cell in table.select("td"):
        marker = cell.find("em")
        marker_text = _node_text(marker) if isinstance(marker, Tag) else None
        if (marker_text or "").casefold() == label.casefold():
            marker.extract()
            return _node_text(cell)
    return None


def _fight_status(fighters: list[dict[str, Any]]) -> tuple[str, str | None]:
    outcomes = " ".join(fighter.get("outcome") or "" for fighter in fighters)
    if any(fighter.get("winner") for fighter in fighters):
        return "completed", "win"
    if "no contest" in outcomes or "no_contest" in outcomes:
        return "no_contest", "no_contest"
    if "draw" in outcomes:
        return "draw", "draw"
    if "cancel" in outcomes:
        return "cancelled", None
    return "scheduled", None


def _fight_external_id(
    event: dict[str, Any],
    fighter_a: dict[str, Any],
    fighter_b: dict[str, Any],
) -> str:
    fighter_ids = sorted((fighter_a["external_id"], fighter_b["external_id"]))
    return f"{event_external_id(event)}--{fighter_ids[0]}--{fighter_ids[1]}"


def _fight_row(
    event: dict[str, Any],
    node: Tag,
    is_main_event: bool,
) -> dict[str, Any] | None:
    performers = [
        fighter
        for fighter in (
            _fighter_from_performer(performer)
            for performer in node.select('[itemprop="performer"]')
        )
        if fighter is not None
    ]
    if len(performers) != 2:
        return None
    fighter_a, fighter_b = performers
    status, result_type = _fight_status(performers)
    weight = _node_text(node.select_one(".weight_class"))

    method: str | None = None
    finish_round: int | None = None
    finish_time: str | None = None
    if is_main_event:
        resume = node.select_one(".fight_card_resume")
        method = _resume_value(resume, "Method")
        round_value = _resume_value(resume, "Round")
        finish_time = _resume_value(resume, "Time")
    else:
        method = _node_text(node.select_one(".winby b"))
        cells = node.find_all("td", recursive=False)
        round_value = _node_text(cells[-2]) if len(cells) >= 2 else None
        finish_time = _node_text(cells[-1]) if cells else None

    try:
        finish_round = int(round_value) if round_value else None
    except ValueError:
        finish_round = None

    scheduled_rounds = 5 if (finish_round or 0) > 3 else 3
    return {
        "external_id": _fight_external_id(event, fighter_a, fighter_b),
        "fighter_a": fighter_a,
        "fighter_b": fighter_b,
        "weight_class": weight,
        "scheduled_rounds": scheduled_rounds,
        "is_title_fight": scheduled_rounds == 5,
        "ruleset": "MMA",
        "bout_type": f"{weight} MMA Bout" if weight else "MMA Bout",
        "fight_status": status,
        "result_type": result_type,
        "method": method,
        "finish_round": finish_round,
        "finish_time_seconds": _time_seconds(finish_time),
    }


def parse_sherdog_fights(
    event: dict[str, Any],
    html: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    fights: list[dict[str, Any]] = []

    main_card = soup.select_one(".fight_card")
    if isinstance(main_card, Tag):
        main_container = main_card.find_parent(
            attrs={"itemprop": "subEvent"}
        )
        if isinstance(main_container, Tag):
            main = _fight_row(event, main_container, is_main_event=True)
            if main:
                fights.append(main)

    table_rows = soup.select(
        'table.new_table.upcoming tr[itemprop="subEvent"], '
        'table.new_table.result tr[itemprop="subEvent"]'
    )
    for row in table_rows:
        fight = _fight_row(event, row, is_main_event=False)
        if fight:
            fights.append(fight)

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for fight in fights:
        external_id = fight_external_id(fight)
        if external_id not in seen:
            seen.add(external_id)
            unique.append(fight)
    return unique


def fight_external_id(fight: dict[str, Any]) -> str:
    value = _text(fight.get("external_id"))
    if not value:
        raise ValueError("LFA fight is missing its id.")
    return value


def fighters(fight: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fighter_a = fight.get("fighter_a")
    fighter_b = fight.get("fighter_b")
    if not isinstance(fighter_a, dict) or not isinstance(fighter_b, dict):
        raise ValueError(f"LFA fight {fight_external_id(fight)} has incomplete fighters.")
    return fighter_a, fighter_b


def normalized_status(fight: dict[str, Any]) -> str:
    return _text(fight.get("fight_status")) or "scheduled"


def winner_external_id(fight: dict[str, Any]) -> str | None:
    for fighter in fighters(fight):
        if fighter.get("winner") is True:
            return _text(fighter.get("external_id"))
    return None
