from __future__ import annotations

import html as html_module
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag


BKFC_BASE_URL = "https://www.bkfc.com"
EASTERN_TIMEZONE = ZoneInfo("America/New_York")
DASHBOARD_TIMEZONE = ZoneInfo("America/Chicago")
EVENT_DATE_FORMAT = "%B %d, %Y %I:%M %p"
STATS_PATTERN = re.compile(
    r"const\s+(FINAL_STATS|LIVE_STATS)\s*=\s*'([^']*)'\s*;",
    re.I,
)
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


def _absolute_url(value: str | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    if text.startswith("/"):
        return BKFC_BASE_URL + text
    return text


def _slug(value: str | None) -> str | None:
    text = _text(value)
    if not text:
        return None
    path = urlparse(text).path.rstrip("/")
    return path.rsplit("/", 1)[-1] or None


def _smart_name(value: str | None) -> str | None:
    text = _text(value)
    if not text or not text.isupper():
        return text
    words: list[str] = []
    for word in text.split():
        bare = re.sub(r"[^A-Z]", "", word)
        if len(bare) == 2:
            words.append(word)
        else:
            words.append(word.title())
    return " ".join(words)


def _event_datetime(value: str) -> datetime:
    parsed = datetime.strptime(value, EVENT_DATE_FORMAT)
    return parsed.replace(tzinfo=EASTERN_TIMEZONE).astimezone(timezone.utc)


def _split_location(value: str | None) -> dict[str, str | None]:
    text = _text(value)
    if not text:
        return {
            "venue": None,
            "city": None,
            "state_region": None,
            "country": None,
        }
    venue, separator, location = text.partition(" - ")
    if not separator:
        return {
            "venue": text,
            "city": None,
            "state_region": None,
            "country": None,
        }
    parts = [part.strip() for part in location.split(",") if part.strip()]
    city = parts[0] if parts else None
    region = parts[1] if len(parts) > 1 else None
    country = None
    if region:
        if re.fullmatch(r"[A-Z]{2}", region):
            country = "United States"
        elif region.casefold() in {"uk", "england", "scotland", "wales"}:
            country = "United Kingdom"
        else:
            country = region.title()
            region = None
    return {
        "venue": venue,
        "city": city.title() if city and city.isupper() else city,
        "state_region": region,
        "country": country,
    }


def _watch_platform(labels: Iterable[str | None]) -> str:
    platforms: list[str] = []
    for raw in labels:
        value = (_text(raw) or "").casefold()
        label = None
        if "dazn" in value:
            label = "DAZN"
        elif "fubo" in value:
            label = "Fubo Sports"
        elif "bkfc" in value:
            label = "BKFC+"
        if label and label not in platforms:
            platforms.append(label)
    return " / ".join(platforms) if platforms else "BKFC+"


def parse_event_listing(html: str, status: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    events: dict[str, dict[str, Any]] = {}
    for card in soup.select(".events_item"):
        title_node = card.select_one(".events_card_heading")
        date_node = card.select_one("[data-event-date-est]")
        if not isinstance(title_node, Tag) or not isinstance(date_node, Tag):
            continue
        link = title_node.find_parent("a", href=True)
        if not isinstance(link, Tag):
            link = card.select_one('a[href^="/events/"]')
        name = _node_text(title_node)
        date_text = _node_text(date_node)
        url = _absolute_url(_text(link.get("href")) if link else None)
        external_id = _slug(url)
        if not name or not date_text or not url or not external_id:
            continue
        location_node = card.select_one(".events_card_location p")
        platform_labels = [
            _text(image.get("alt"))
            for image in card.select(".events_card_partners img[alt]")
        ]
        events[external_id] = {
            "external_id": external_id,
            "name": name,
            "date": _event_datetime(date_text),
            "external_url": url,
            "status": status,
            "watch_platform": _watch_platform(platform_labels),
            **_split_location(_node_text(location_node)),
        }
    if not events:
        raise ValueError("BKFC event listing contains no recognizable events.")
    return list(events.values())


def merge_event_listings(*groups: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    events: dict[str, dict[str, Any]] = {}
    for group in groups:
        for event in group:
            external_id = event_external_id(event)
            current = events.get(external_id)
            if current is None or event_status(event) == "completed":
                events[external_id] = dict(event)
    return list(events.values())


def enrich_event(event: dict[str, Any], html: str) -> dict[str, Any]:
    enriched = dict(event)
    soup = BeautifulSoup(html, "html.parser")
    location_node = soup.select_one(
        ".hero-event-card_meta_item p.text-size-1-25"
    )
    if isinstance(location_node, Tag):
        location = _split_location(_node_text(location_node))
        for field, value in location.items():
            if value:
                enriched[field] = value
    labels = [
        _text(image.get("alt"))
        for image in soup.select(
            ".hero-event-card img[alt], .evnts_header-block_icons img[alt]"
        )
    ]
    if labels:
        enriched["watch_platform"] = _watch_platform(labels)
    return enriched


def event_stats_url(html: str) -> str | None:
    values = {
        key.upper(): html_module.unescape(value).strip()
        for key, value in STATS_PATTERN.findall(html)
    }
    return values.get("FINAL_STATS") or values.get("LIVE_STATS") or None


def event_external_id(event: dict[str, Any]) -> str:
    value = _text(event.get("external_id"))
    if not value:
        raise ValueError("BKFC event is missing its id.")
    return value


def event_name(event: dict[str, Any]) -> str:
    value = _text(event.get("name"))
    if not value:
        raise ValueError(f"BKFC event {event_external_id(event)} has no name.")
    return value


def event_datetime(event: dict[str, Any]) -> datetime:
    value = event.get("date")
    if not isinstance(value, datetime):
        raise ValueError(f"BKFC event {event_external_id(event)} has no date.")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def dashboard_event_date(event: dict[str, Any]) -> date:
    return event_datetime(event).astimezone(DASHBOARD_TIMEZONE).date()


def event_in_window(event: dict[str, Any], start: date, end: date) -> bool:
    current = dashboard_event_date(event)
    return start <= current <= end


def event_status(event: dict[str, Any]) -> str:
    value = _text(event.get("status"))
    return value if value in {"upcoming", "live", "completed"} else "upcoming"


def event_location(event: dict[str, Any]) -> dict[str, str | None]:
    return {
        field: _text(event.get(field))
        for field in ("venue", "city", "state_region", "country")
    }


def event_external_url(event: dict[str, Any]) -> str | None:
    return _absolute_url(_text(event.get("external_url")))


def is_outcome_control_label(value: str | None) -> bool:
    text = (_text(value) or "").casefold()
    if not text:
        return True
    remainder = re.sub(
        r"\b(?:win|loss|lose|draw|no\s+contest)\b",
        " ",
        text,
    )
    return not re.sub(r"[^a-z0-9]+", "", remainder)


def _fighter_link_name(link: Tag) -> str | None:
    name_node = link.select_one(".fight-card_name")
    if isinstance(name_node, Tag):
        name = _node_text(name_node)
        if not is_outcome_control_label(name):
            return name
    aria_label = _text(link.get("aria-label"))
    if not is_outcome_control_label(aria_label):
        return aria_label
    value = _node_text(link)
    if is_outcome_control_label(value):
        return None
    return value


def _unique_fighter_links(bout: Tag) -> list[Tag]:
    links: list[Tag] = []
    positions: dict[str, int] = {}
    for link in bout.select('a[href^="/fighters/"]'):
        href = _text(link.get("href"))
        if not href:
            continue
        if href not in positions:
            positions[href] = len(links)
            links.append(link)
        elif not _fighter_link_name(links[positions[href]]) and _fighter_link_name(link):
            links[positions[href]] = link
    return links


def _stats_bouts(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    bouts = payload.get("Bouts")
    if not isinstance(bouts, dict):
        return []
    return [row for row in bouts.values() if isinstance(row, dict)]


def _stats_for_sides(
    rows: list[dict[str, Any]],
    blue_uuid: str | None,
    red_uuid: str | None,
    blue_name: str,
    red_name: str,
) -> dict[str, Any] | None:
    for row in rows:
        if (
            blue_uuid
            and red_uuid
            and row.get("AthleteBlueUUID") == blue_uuid
            and row.get("AthleteRedUUID") == red_uuid
        ):
            return row
    target = {
        re.sub(r"[^a-z0-9]+", "", blue_name.casefold()),
        re.sub(r"[^a-z0-9]+", "", red_name.casefold()),
    }
    for row in rows:
        names = {
            re.sub(
                r"[^a-z0-9]+",
                "",
                f"{row.get('BlueFirstName', '')} {row.get('BlueLastName', '')}".casefold(),
            ),
            re.sub(
                r"[^a-z0-9]+",
                "",
                f"{row.get('RedFirstName', '')} {row.get('RedLastName', '')}".casefold(),
            ),
        }
        if names == target:
            return row
    return None


def _result_status(stats: dict[str, Any] | None) -> str:
    if not stats:
        return "scheduled"
    values = {
        (_text(stats.get("BlueResult")) or "").casefold(),
        (_text(stats.get("RedResult")) or "").casefold(),
    }
    method = (_text(stats.get("WinMethod")) or "").casefold()
    if "no contest" in values or "no contest" in method:
        return "no_contest"
    if "draw" in values or "draw" in method:
        return "draw"
    if "win" in values or "lose" in values or method:
        return "completed"
    return "scheduled"


def _result_type(method: str | None, status: str) -> str | None:
    value = (method or "").casefold()
    if status == "draw":
        return "draw"
    if status == "no_contest":
        return "no_contest"
    if "tko" in value:
        return "tko"
    if re.search(r"\bko\b", value):
        return "ko"
    if "decision" in value:
        return "decision"
    return "other" if value else None


def _finish_seconds(value: Any) -> int | None:
    text = _text(value)
    if not text:
        return None
    match = TIME_PATTERN.match(text)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _scheduled_rounds(stats: dict[str, Any] | None) -> int:
    if not stats:
        return 5
    try:
        total = int(stats.get("TotalRounds") or 0)
    except (TypeError, ValueError):
        return 5
    # MMAReg includes BKFC's possible sudden-death round in TotalRounds.
    return total - 1 if total in {4, 6} else total or 5


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().casefold() in {
        "1", "true", "yes"
    }


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value)
        return result if result > 0 else None
    except (TypeError, ValueError):
        return None


def parse_fights(
    event: dict[str, Any],
    html: str,
    stats_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    stats_rows = _stats_bouts(stats_payload)
    fights: list[dict[str, Any]] = []
    for bout in soup.select("[data-bout]"):
        links = _unique_fighter_links(bout)
        if len(links) < 2:
            continue
        blue_name = _smart_name(_fighter_link_name(links[0]))
        red_name = _smart_name(_fighter_link_name(links[1]))
        if not blue_name or not red_name:
            continue
        blue_uuid = _text(bout.get("data-athleteblueuuid"))
        red_uuid = _text(bout.get("data-athletereduuid"))
        stats = _stats_for_sides(
            stats_rows, blue_uuid, red_uuid, blue_name, red_name
        )
        if stats:
            # Keep the public card's display names. MMAReg can use a legal
            # name that will not match the already-saved card identity.
            blue_uuid = _text(stats.get("AthleteBlueUUID")) or blue_uuid
            red_uuid = _text(stats.get("AthleteRedUUID")) or red_uuid
        blue_external = blue_uuid or _slug(_text(links[0].get("href")))
        red_external = red_uuid or _slug(_text(links[1].get("href")))
        if not blue_external or not red_external:
            continue
        headings = [
            _node_text(node)
            for node in bout.select(".fight-card_header .fight-card_heading")
        ]
        headings = [heading for heading in headings if heading]
        role = headings[0] if headings else None
        weight = _text(stats.get("Weightclass")) if stats else None
        if not weight and headings:
            weight = headings[-1] if len(headings) > 1 else None
        is_title = bool(stats and _flag(stats.get("ChampionshipBout"))) or bool(
            role and any(word in role.casefold() for word in ("title", "championship"))
        )
        status = _result_status(stats)
        method = _text(stats.get("WinMethod")) if stats else None
        technique = _text(stats.get("WinTechnique")) if stats else None
        if technique and technique.casefold() not in (method or "").casefold():
            method = f"{method} ({technique})" if method else technique
        blue_result = (_text(stats.get("BlueResult")) or "").casefold() if stats else ""
        red_result = (_text(stats.get("RedResult")) or "").casefold() if stats else ""
        bout_external = (
            (_text(stats.get("BoutUUID")) if stats else None)
            or (_text(stats.get("BoutID")) if stats else None)
            or f"{event_external_id(event)}:{blue_external}:{red_external}"
        )
        bout_label = (
            f"{weight} BKFC Championship Bout"
            if weight and is_title
            else f"{weight} Bare Knuckle Bout"
            if weight
            else "Bare Knuckle Bout"
        )
        fights.append(
            {
                "external_id": bout_external,
                "fighter_a": {
                    "external_id": blue_external,
                    "external_url": _absolute_url(_text(links[0].get("href"))),
                    "name": blue_name,
                    "winner": blue_result == "win",
                },
                "fighter_b": {
                    "external_id": red_external,
                    "external_url": _absolute_url(_text(links[1].get("href"))),
                    "name": red_name,
                    "winner": red_result == "win",
                },
                "weight_class": weight,
                "scheduled_rounds": _scheduled_rounds(stats),
                "is_title_fight": is_title,
                "ruleset": "Bare Knuckle Boxing",
                "results_source_matched": stats is not None,
                "bout_type": bout_label,
                "fight_status": status,
                "result_type": _result_type(method, status),
                "method": method,
                "finish_round": _positive_int(stats.get("RoundEnded"))
                if stats
                else None,
                "finish_time_seconds": _finish_seconds(
                    stats.get("RoundEndedTime") if stats else None
                ),
            }
        )
    return fights


def fight_external_id(fight: dict[str, Any]) -> str:
    value = _text(fight.get("external_id"))
    if not value:
        raise ValueError("BKFC fight is missing its id.")
    return value


def fighters(fight: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    fighter_a = fight.get("fighter_a")
    fighter_b = fight.get("fighter_b")
    if not isinstance(fighter_a, dict) or not isinstance(fighter_b, dict):
        raise ValueError(
            f"BKFC fight {fight_external_id(fight)} has incomplete fighters."
        )
    return fighter_a, fighter_b


def normalized_status(fight: dict[str, Any]) -> str:
    return _text(fight.get("fight_status")) or "scheduled"


def winner_external_id(fight: dict[str, Any]) -> str | None:
    for fighter in fighters(fight):
        if fighter.get("winner") is True:
            return _text(fighter.get("external_id"))
    return None
