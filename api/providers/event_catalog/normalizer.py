from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup


MONTHS = {
    month.casefold(): number
    for number, month in enumerate(
        (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ),
        start=1,
    )
}
MONTHS.update({name[:3]: number for name, number in list(MONTHS.items())})
WEEKDAYS = {name: number for number, name in enumerate(
    ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
)}
EVENT_PATH = re.compile(r"^/(?:event|events)/[^/]+/?$", re.I)


def normalized_text(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    if "T" in text:
        try:
            instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if instant.tzinfo:
                return instant.astimezone(ZoneInfo("America/Chicago")).date()
        except ValueError:
            pass
    iso = re.search(r"(20\d{2})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return date.fromisoformat(iso.group(0))
        except ValueError:
            return None
    written = re.search(
        r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,|\s)\s*(20\d{2})\b",
        text,
        re.I,
    )
    if written:
        try:
            return date(
                int(written.group(3)),
                MONTHS[written.group(1).casefold().rstrip(".")],
                int(written.group(2)),
            )
        except ValueError:
            return None
    return None


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _event_url(value: Any, base_url: str) -> str | None:
    if isinstance(value, dict):
        value = _first(value, "url", "href", "path", "slug")
    text = str(value or "").strip()
    if not text:
        return None
    if not text.startswith(("http://", "https://", "/")):
        text = "/events/" + text.strip("/")
    url = urljoin(base_url, text)
    parsed = urlparse(url)
    trusted_hosts = {"www.ufc.com", "ufc.com", "pflmma.com", "www.pflmma.com"}
    if parsed.scheme != "https" or parsed.hostname not in trusted_hosts:
        return None
    return url.split("#", 1)[0].split("?", 1)[0]


def _promotion_key(catalog: str, name: str) -> str:
    if catalog == "ufc" and "contender series" in normalized_text(name):
        return "dwcs"
    return catalog


def _external_id(key: str, url: str | None, name: str, event_date: date) -> str:
    if url:
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
        if slug:
            return f"{key}:{slug}"
    digest = hashlib.sha256(f"{key}|{event_date}|{normalized_text(name)}".encode()).hexdigest()[:20]
    return f"{key}:{digest}"


def _entry(
    catalog: str,
    name: Any,
    event_date: date | None,
    url: Any,
    base_url: str,
) -> dict[str, Any] | None:
    clean_name = " ".join(str(name or "").split())
    if not clean_name or not event_date:
        return None
    normalized = normalized_text(clean_name)
    if catalog == "ufc" and not any(token in normalized for token in ("ufc", "contender series")):
        return None
    if catalog == "pfl" and not any(
        token in normalized for token in ("pfl", "professional fighters league")
    ):
        # The official PFL catalog sometimes publishes sub-brand cards as
        # "Champions Series", "Africa: Semifinals", or simply "Finals".
        # They are still authoritative PFL events because the candidate comes
        # from a dated /event link on the official catalog.
        clean_name = f"PFL {clean_name}"
    clean_url = _event_url(url, base_url)
    key = _promotion_key(catalog, clean_name)
    return {
        "promotion_key": key,
        "name": clean_name,
        "date": event_date,
        "external_url": clean_url,
        "external_id": _external_id(key, clean_url, clean_name, event_date),
    }


def _timestamp_date(value: Any) -> date | None:
    try:
        instant = datetime.fromtimestamp(int(str(value)), timezone.utc)
        if not 2000 <= instant.year <= 2100:
            return None
        return instant.astimezone(ZoneInfo("America/Chicago")).date()
    except (ValueError, OverflowError, OSError):
        return None


def _ufc_title(name: str, url: str) -> str:
    if re.search(r"\bufc\b|contender series", name, re.I):
        return name
    slug = urlparse(url).path.rsplit("/", 1)[-1]
    numbered = re.search(r"(?:^|-)ufc-(\d+)(?:-|$)", slug, re.I)
    if numbered:
        return f"UFC {numbered.group(1)}: {name}"
    if "ufc-fight-night" in slug or "ufc-on-" in slug:
        return f"UFC Fight Night: {name}"
    if "contender-series" in slug or "dwcs" in slug:
        season_week = re.search(r"season-(\d+)-week-(\d+)", slug)
        if season_week:
            return ("Dana White's Contender Series: Season " + season_week.group(1)
                    + ", Week " + season_week.group(2))
        return f"Dana White's Contender Series: {name}"
    if "road-to-ufc" in slug:
        return f"Road to UFC: {name}"
    return name


def _pfl_partial_date(text: str, url: str, section: str, today: date) -> date | None:
    """Use section direction and weekday to resolve a missing year, never archives."""
    written = re.search(
        r"\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
        text, re.I,
    )
    weekday = re.search(
        r"\b(mon(?:day)?|tue(?:sday)?|wed(?:nesday)?|thu(?:rsday)?|"
        r"fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b", text, re.I,
    )
    if not written or not weekday:
        return None
    years = set(re.findall(r"(?<!\d)(20\d{2})(?!\d)", urlparse(url).path))
    if len(years) > 1:
        return None
    if len(years) == 1:
        candidates = [int(next(iter(years)))]
    elif section == "nav-upcoming":
        candidates = [today.year, today.year + 1]
    elif section == "nav-past":
        candidates = [today.year, today.year - 1]
    else:
        return None
    for year in candidates:
        try:
            day = date(year, MONTHS[written.group(1).lower().rstrip(".")], int(written.group(2)))
        except ValueError:
            continue
        if day.weekday() != WEEKDAYS[weekday.group(1).lower()[:3]]:
            continue
        if section == "nav-upcoming" and not 0 <= (day - today).days <= 366:
            continue
        if section == "nav-past" and not 0 <= (today - day).days <= 366:
            continue
        return day
    return None


def _visible_schedule(soup, catalog: str, base_url: str, today: date):
    selector = ".c-card-event--result__info" if catalog == "ufc" else ".event-card-info"
    for card in soup.select(selector):
        heading = card.select_one("h3")
        if heading is None:
            continue
        links = heading.find_all("a", href=True) if catalog == "ufc" else card.find_all("a", href=True)
        url = next((url for link in links
                    if (url := _event_url(link.get("href"), base_url))
                    and EVENT_PATH.match(urlparse(url).path)), None)
        if not url:
            continue
        name = heading.get_text(" ", strip=True)
        if catalog == "ufc":
            date_node = card.select_one(".c-card-event--result__date")
            if date_node is None:
                continue
            event_date = _timestamp_date(date_node.get("data-main-card-timestamp"))
            # A missing/invalid main-card value may use the event's prelim start.
            # Ticket-sale timestamps elsewhere in the listing are never used.
            if event_date is None:
                event_date = _timestamp_date(date_node.get("data-prelims-card-timestamp"))
            name = _ufc_title(name, url)
        else:
            date_node = card.select_one("time, h6")
            if date_node is None:
                continue
            text = date_node.get_text(" ", strip=True)
            event_date = _date(date_node.get("datetime")) or _date(text)
            if event_date is None:
                section = next((p.get("id") for p in card.parents
                                if p.get("id") in {"nav-upcoming", "nav-past", "nav-all"}), "")
                event_date = _pfl_partial_date(text, url, section, today)
        candidate = _entry(catalog, name, event_date, url, base_url)
        if candidate:
            yield candidate


def parse_official_catalog(
    html: str,
    catalog: str,
    base_url: str,
    *,
    reference_date: date | None = None,
) -> list[dict[str, Any]]:
    if catalog not in {"ufc", "pfl"}:
        raise ValueError("Official catalog must be UFC or PFL.")
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, Any]] = []
    today = reference_date or datetime.now(ZoneInfo("America/Chicago")).date()

    for script in soup.select('script[type="application/ld+json"], script#__NEXT_DATA__'):
        try:
            payload = json.loads(script.get_text(strip=True))
        except (TypeError, ValueError):
            continue
        for row in _walk(payload):
            row_type = normalized_text(row.get("@type"))
            name = _first(row, "name", "eventName", "event_name", "title", "label")
            raw_date = _first(row, "startDate", "start_date", "eventDate", "event_date", "date")
            event_date = _date(raw_date)
            if row_type and row_type not in {"event", "sportsevent"} and not event_date:
                continue
            candidate = _entry(
                catalog,
                name,
                event_date,
                _first(row, "url", "href", "eventUrl", "event_url", "slug"),
                base_url,
            )
            if candidate:
                candidates.append(candidate)

    candidates.extend(_visible_schedule(soup, catalog, base_url, today))

    link_pattern = re.compile(r"/(?:event|events)/[^/#?]+", re.I)
    for link in soup.find_all("a", href=link_pattern):
        if link.find_parent(class_="event-card-info") or link.find_parent(class_="c-card-event--result__info"):
            continue
        clean_url = _event_url(link.get("href"), base_url)
        if not clean_url or not EVENT_PATH.match(urlparse(clean_url).path):
            continue
        container = link
        event_date = None
        text = ""
        for _ in range(5):
            other_urls = {_event_url(a.get("href"), base_url) for a in container.find_all("a", href=link_pattern)}
            if len(other_urls - {None, clean_url}) > 0:
                break  # Never borrow another event's title/date from a shared parent.
            text = " ".join(container.get_text(" ", strip=True).split())
            time_node = container.find("time") if hasattr(container, "find") else None
            event_date = _date(time_node.get("datetime") if time_node else None) or _date(text)
            if event_date:
                break
            if not container.parent:
                break
            container = container.parent
        heading = link.find(["h1", "h2", "h3", "h4"])
        if heading is None and hasattr(container, "find"):
            heading = container.find(["h1", "h2", "h3", "h4"])
        name = heading.get_text(" ", strip=True) if heading else link.get_text(" ", strip=True)
        candidate = _entry(catalog, name, event_date, clean_url, base_url)
        if candidate:
            candidates.append(candidate)

    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in candidates:
        identity = (
            candidate["promotion_key"],
            candidate["external_id"],
        )
        existing = unique.get(identity)
        if not existing or (not existing.get("external_url") and candidate.get("external_url")):
            unique[identity] = candidate
    return sorted(unique.values(), key=lambda row: (row["date"], row["name"]))
