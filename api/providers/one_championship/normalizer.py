from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag


DASHBOARD_TIMEZONE = ZoneInfo("America/Chicago")
EVENT_PATH_PATTERN = re.compile(r"^/events/([^/]+)/?$")
ATHLETE_PATH_PATTERN = re.compile(r"^/athletes/([^/]+)/?$")
ROUND_PATTERN = re.compile(r"^(.*?)\s*\(R(\d+)\)\s*$", re.IGNORECASE)
STATUS_URL_PATTERN = re.compile(
    r"window\.eventStatusUrl\s*=\s*['\"]([^'\"]+)['\"]"
)
WEIGHT_CLASSES = (
    "Light Heavyweight",
    "Atomweight",
    "Strawweight",
    "Flyweight",
    "Bantamweight",
    "Featherweight",
    "Lightweight",
    "Welterweight",
    "Middleweight",
    "Heavyweight",
    "Openweight",
    "Catchweight",
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _node_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    return _text(node.get_text(" ", strip=True))


def _slug(url: str | None, pattern: re.Pattern[str]) -> str | None:
    if not url:
        return None
    match = pattern.match(urlparse(url).path)
    return match.group(1) if match else None


def _event_schema(soup: BeautifulSoup) -> dict[str, Any]:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue

        candidates: list[Any] = [payload]
        if isinstance(payload, dict) and isinstance(payload.get("@graph"), list):
            candidates.extend(payload["@graph"])

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            schema_type = candidate.get("@type")
            if schema_type == "Event" or (
                isinstance(schema_type, list) and "Event" in schema_type
            ):
                return candidate
    return {}


def parse_event_listing(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    events_by_id: dict[str, dict[str, Any]] = {}

    for card in soup.select(".simple-post-card.is-event"):
        link = card.select_one("a.title[href]")
        timestamp_node = card.select_one("[data-timestamp]")
        if not isinstance(link, Tag) or not isinstance(timestamp_node, Tag):
            continue

        event_url = _text(link.get("href"))
        external_id = _slug(event_url, EVENT_PATH_PATTERN)
        timestamp = _text(timestamp_node.get("data-timestamp"))
        name = _text(link.get("title")) or _node_text(link)
        if not external_id or not timestamp or not name or not event_url:
            continue

        try:
            event_time = datetime.fromtimestamp(int(timestamp), timezone.utc)
        except (TypeError, ValueError, OverflowError):
            continue

        events_by_id[external_id] = {
            "external_id": external_id,
            "name": name,
            "date": event_time,
            "external_url": event_url,
            "location_text": _node_text(card.select_one(".location")),
            "status": "upcoming",
        }

    if not events_by_id:
        raise ValueError(
            "ONE Championship event listing contains no recognizable events."
        )
    return list(events_by_id.values())


def event_external_id(event: dict[str, Any]) -> str:
    value = _text(event.get("external_id"))
    if not value:
        raise ValueError("ONE Championship event is missing its id.")
    return value


def event_name(event: dict[str, Any]) -> str:
    value = _text(event.get("name"))
    if not value:
        raise ValueError(
            f"ONE Championship event {event_external_id(event)} has no name."
        )
    return value


def event_datetime(event: dict[str, Any]) -> datetime:
    value = event.get("date")
    if not isinstance(value, datetime):
        raise ValueError(
            f"ONE Championship event {event_external_id(event)} has no date."
        )
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dashboard_event_date(event: dict[str, Any]) -> date:
    return event_datetime(event).astimezone(DASHBOARD_TIMEZONE).date()


def event_in_window(event: dict[str, Any], start: date, end: date) -> bool:
    current = dashboard_event_date(event)
    return start <= current <= end


def event_status_url(html: str) -> str | None:
    match = STATUS_URL_PATTERN.search(html)
    return match.group(1) if match else None


def _page_status(status_payload: dict[str, Any] | None) -> str:
    payload = status_payload or {}
    if payload.get("is_finished") is True:
        return "completed"
    if payload.get("is_past") is True:
        return "live"
    return "upcoming"


def _location_from_schema(schema: dict[str, Any]) -> dict[str, str | None]:
    location = schema.get("location") or {}
    if not isinstance(location, dict):
        return {"venue": None, "city": None, "state_region": None, "country": None}
    address = location.get("address") or {}
    if not isinstance(address, dict):
        return {"venue": None, "city": None, "state_region": None, "country": None}
    return {
        "venue": _text(location.get("name")),
        "city": _text(address.get("addressLocality")),
        "state_region": _text(address.get("addressRegion")),
        "country": _text(address.get("addressCountry")),
    }


def _fallback_location(value: str | None) -> dict[str, str | None]:
    parts = [part.strip() for part in (value or "").split(",") if part.strip()]
    return {
        "venue": parts[0] if parts else None,
        "city": parts[-1] if len(parts) > 1 else None,
        "state_region": None,
        "country": None,
    }


def watch_platform(event: dict[str, Any]) -> str:
    name = event_name(event).casefold()
    if "fight night" in name:
        return "Prime Video"
    if "friday fights" in name:
        return "ONE Championship / YouTube"
    return "ONE Championship"


def enrich_event(
    event: dict[str, Any],
    html: str,
    status_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    schema = _event_schema(soup)
    schema_location = _location_from_schema(schema)
    fallback = _fallback_location(_text(event.get("location_text")))
    location = {
        key: schema_location.get(key) or fallback.get(key)
        for key in ("venue", "city", "state_region", "country")
    }
    return {
        **event,
        "status": _page_status(status_payload),
        "watch_platform": watch_platform(event),
        **location,
    }


def event_status(event: dict[str, Any]) -> str:
    value = _text(event.get("status"))
    return value if value in {"upcoming", "live", "completed"} else "upcoming"


def event_location(event: dict[str, Any]) -> dict[str, str | None]:
    return {
        key: _text(event.get(key))
        for key in ("venue", "city", "state_region", "country")
    }


def event_external_url(event: dict[str, Any]) -> str | None:
    return _text(event.get("external_url"))


def ruleset(bout_type: str | None) -> str:
    value = (bout_type or "").casefold()
    if "muay thai" in value:
        return "Muay Thai"
    if "kickboxing" in value:
        return "Kickboxing"
    if "submission grappling" in value or "grappling" in value:
        return "Submission Grappling"
    if re.search(r"\bmma\b", value):
        return "MMA"
    return "Other"


def weight_class(bout_type: str | None) -> str | None:
    value = bout_type or ""
    prefix = "Women's " if re.search(r"\bwomen(?:'s|s)?\b", value, re.I) else ""
    for candidate in WEIGHT_CLASSES:
        if re.search(rf"\b{re.escape(candidate)}\b", value, re.I):
            return prefix + candidate
    return None


def is_title_fight_value(bout_type: str | None) -> bool:
    value = (bout_type or "").casefold()
    return "world championship" in value or "world title" in value


def scheduled_rounds_value(bout_type: str | None) -> int:
    if ruleset(bout_type) == "Submission Grappling":
        return 1
    return 5 if is_title_fight_value(bout_type) else 3


def _athlete(
    name: str,
    link: str | None,
    winner: bool,
) -> dict[str, Any]:
    external_id = _slug(link, ATHLETE_PATH_PATTERN)
    if not external_id:
        external_id = "name-" + re.sub(
            r"[^a-z0-9]+", "-", name.casefold()
        ).strip("-")
    return {
        "external_id": external_id,
        "name": name,
        "winner": winner,
        "external_url": link,
    }


def _result_details(matchup: Tag) -> tuple[str | None, int | None]:
    winner_sticker = matchup.select_one(".sticker.is-win")
    if not isinstance(winner_sticker, Tag):
        return None, None
    detail = winner_sticker.select_one(".opacity-50.d-none")
    if detail is None:
        detail = winner_sticker.select_one(".opacity-50")
    result = _node_text(detail)
    if not result:
        return None, None
    match = ROUND_PATTERN.match(result)
    if not match:
        return result, None
    return _text(match.group(1)), int(match.group(2))


def parse_fights(event: dict[str, Any], html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    fights: list[dict[str, Any]] = []

    for matchup in soup.select(".event-matchup"):
        cells = matchup.select(".stats tr.vs td")
        faces = matchup.select("a.face")
        if len(cells) != 2:
            continue

        names: list[str] = []
        links: list[str | None] = []
        winners: list[bool] = []
        for index, cell in enumerate(cells):
            athlete_link = cell.select_one("a")
            name = (
                _text(athlete_link.get("title"))
                if isinstance(athlete_link, Tag)
                else None
            ) or _node_text(cell)
            link = (
                _text(athlete_link.get("href"))
                if isinstance(athlete_link, Tag)
                else None
            )
            face = faces[index] if index < len(faces) else None
            winner = isinstance(face, Tag) and face.select_one(".sticker.is-win") is not None
            if not name:
                break
            names.append(name)
            links.append(link)
            winners.append(winner)
        if len(names) != 2:
            continue

        label_node = matchup.find("div", class_="title", recursive=False)
        bout_type = _node_text(label_node)
        fighter_a = _athlete(names[0], links[0], winners[0])
        fighter_b = _athlete(names[1], links[1], winners[1])
        method, finish_round = _result_details(matchup)
        sticker_text = " ".join(
            node.get_text(" ", strip=True)
            for node in matchup.select(".sticker")
        ).casefold()

        if any(token in sticker_text for token in ("cancelled", "canceled", "withdrawn", "postponed")):
            status = "cancelled"
            result_type = None
        elif any(winners):
            status = "completed"
            result_type = "win"
        elif "no contest" in sticker_text:
            status = "no_contest"
            result_type = "no_contest"
        elif "draw" in sticker_text:
            status = "draw"
            result_type = "draw"
        else:
            status = "scheduled"
            result_type = None

        fight_id_parts = sorted(
            (fighter_a["external_id"], fighter_b["external_id"])
        )
        fights.append(
            {
                "external_id": (
                    f"{event_external_id(event)}--"
                    f"{fight_id_parts[0]}--{fight_id_parts[1]}"
                ),
                "fighter_a": fighter_a,
                "fighter_b": fighter_b,
                "bout_type": bout_type,
                "ruleset": ruleset(bout_type),
                "weight_class": weight_class(bout_type),
                "scheduled_rounds": scheduled_rounds_value(bout_type),
                "is_title_fight": is_title_fight_value(bout_type),
                "fight_status": status,
                "result_type": result_type,
                "method": method,
                "finish_round": finish_round,
                "finish_time_seconds": None,
            }
        )

    return fights


def fight_external_id(fight: dict[str, Any]) -> str:
    value = _text(fight.get("external_id"))
    if not value:
        raise ValueError("ONE Championship fight is missing its id.")
    return value


def fighters(fight: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fighter_a = fight.get("fighter_a")
    fighter_b = fight.get("fighter_b")
    if not isinstance(fighter_a, dict) or not isinstance(fighter_b, dict):
        raise ValueError(
            f"ONE Championship fight {fight_external_id(fight)} has incomplete fighters."
        )
    return fighter_a, fighter_b


def normalized_status(fight: dict[str, Any]) -> str:
    value = _text(fight.get("fight_status"))
    return value or "scheduled"


def winner_external_id(fight: dict[str, Any]) -> str | None:
    for fighter in fighters(fight):
        if fighter.get("winner") is True:
            return _text(fighter.get("external_id"))
    return None
