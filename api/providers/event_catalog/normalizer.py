from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
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


def parse_official_catalog(
    html: str,
    catalog: str,
    base_url: str,
) -> list[dict[str, Any]]:
    if catalog not in {"ufc", "pfl"}:
        raise ValueError("Official catalog must be UFC or PFL.")
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[dict[str, Any]] = []

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

    link_pattern = re.compile(r"/(?:event|events)/[^/#?]+", re.I)
    for link in soup.find_all("a", href=link_pattern):
        container = link
        event_date = None
        text = ""
        for _ in range(5):
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
        candidate = _entry(catalog, name, event_date, link.get("href"), base_url)
        if candidate:
            candidates.append(candidate)

    unique: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        identity = (
            candidate["promotion_key"],
            candidate["external_id"],
        )
        existing = unique.get(identity)
        if not existing or (not existing.get("external_url") and candidate.get("external_url")):
            unique[identity] = candidate
    return sorted(unique.values(), key=lambda row: (row["date"], row["name"]))
