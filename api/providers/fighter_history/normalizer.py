from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


SHERDOG_BASE_URL = "https://www.sherdog.com"
FIGHTER_ID_PATTERN = re.compile(r"-(\d+)(?:/)?$")
EVENT_ID_PATTERN = re.compile(r"-(\d+)(?:/)?$")
TIME_PATTERN = re.compile(r"^(\d+):(\d{2})$")
RECORD_PATTERN = re.compile(r"(\d+)\s*[-–]\s*(\d+)(?:\s*[-–]\s*(\d+))?")
NO_CONTEST_PATTERN = re.compile(r"(\d+)\s*(?:NC|no contests?)", re.I)
GENERATIONAL_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalized_name(value: str | None) -> str:
    without_nickname = re.sub(r'["“][^"”]+["”]', " ", value or "")
    ascii_value = unicodedata.normalize("NFKD", without_nickname).encode(
        "ascii", "ignore"
    ).decode("ascii")
    tokens = re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip().split()
    while tokens and tokens[-1] in GENERATIONAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def names_compatible(left: str | None, right: str | None) -> bool:
    left_key = normalized_name(left)
    right_key = normalized_name(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = left_key.split()
    right_tokens = right_key.split()
    shorter, longer = (
        (left_tokens, right_tokens)
        if len(left_tokens) <= len(right_tokens)
        else (right_tokens, left_tokens)
    )
    return (
        len(shorter) >= 2
        and shorter[-1] == longer[-1]
        and all(token in longer for token in shorter)
    )


def resolved_history_count(history: list[dict[str, Any]]) -> int:
    return sum(
        1
        for entry in history
        if str(entry.get("fight_status") or "").casefold() != "cancelled"
        and str(entry.get("outcome") or "").upper() != "CANCELLED"
    )


def record_total(record: str | None) -> int | None:
    match = RECORD_PATTERN.search(record or "")
    if not match:
        return None
    no_contest = NO_CONTEST_PATTERN.search(record or "")
    return (
        sum(int(value or 0) for value in match.groups())
        + (int(no_contest.group(1)) if no_contest else 0)
    )


def _text(node: Tag | None) -> str | None:
    if not isinstance(node, Tag):
        return None
    value = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    return value or None


def _absolute_url(value: str | None) -> str | None:
    if not value:
        return None
    return urljoin(SHERDOG_BASE_URL, value)


def profile_id_from_url(value: str | None) -> str | None:
    match = FIGHTER_ID_PATTERN.search(urlparse(value or "").path)
    return match.group(1) if match else None


def find_profile_url(
    html: str,
    requested_name: str,
    response_url: str | None = None,
) -> str | None:
    if "/fighter/" in urlparse(response_url or "").path:
        return response_url

    soup = BeautifulSoup(html, "html.parser")
    compatible: list[str] = []
    for link in soup.select('a[href*="/fighter/"]'):
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not href or not names_compatible(_text(link), requested_name):
            continue
        absolute = _absolute_url(str(href))
        if absolute and absolute not in compatible:
            compatible.append(absolute)
    return compatible[0] if len(compatible) == 1 else None


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    for pattern in ("%b / %d / %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _time_seconds(value: str | None) -> int | None:
    match = TIME_PATTERN.match((value or "").strip())
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def _outcome(value: str | None) -> str:
    normalized = normalized_name(value)
    if normalized.startswith("win"):
        return "W"
    if normalized.startswith("loss"):
        return "L"
    if "draw" in normalized:
        return "D"
    if "no contest" in normalized or normalized == "nc":
        return "NC"
    if "cancel" in normalized:
        return "CANCELLED"
    return "—"


def parse_profile_record(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    record = _text(soup.select_one(".record"))
    match = RECORD_PATTERN.search(record or "")
    if not match:
        return None
    return "-".join(value or "0" for value in match.groups())


def _promotion_name(event_name: str | None) -> str:
    normalized = normalized_name(event_name)
    for needle, label in (
        ("dana white s contender series", "DWCS"),
        ("dana whites contender series", "DWCS"),
        ("ufc", "UFC"),
        ("professional fighters league", "PFL"),
        ("pfl", "PFL"),
        ("one championship", "ONE"),
        ("one friday fights", "ONE"),
        ("rizin", "RIZIN"),
        ("legacy fighting alliance", "LFA"),
        ("lfa", "LFA"),
        ("bare knuckle fighting championship", "BKFC"),
        ("bkfc", "BKFC"),
        ("bellator", "Bellator"),
        ("cage warriors", "Cage Warriors"),
    ):
        if normalized.startswith(needle):
            return label
    return "Regional/other"


def _external_bout_id(
    fighter_profile_id: str,
    event_url: str | None,
    opponent_url: str | None,
    event_date: str | None,
) -> str:
    event_match = EVENT_ID_PATTERN.search(urlparse(event_url or "").path)
    opponent_id = profile_id_from_url(opponent_url)
    if event_match and opponent_id:
        return f"{fighter_profile_id}-{event_match.group(1)}-{opponent_id}"
    raw = "|".join(
        value or "" for value in (
            fighter_profile_id,
            event_url,
            opponent_url,
            event_date,
        )
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def parse_profile_history(
    html: str,
    profile_url: str,
    limit: int = 60,
) -> list[dict[str, Any]]:
    fighter_profile_id = profile_id_from_url(profile_url)
    if not fighter_profile_id:
        raise ValueError("Sherdog fighter profile URL has no stable id.")

    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    modules = soup.select("div.module.fight_history, section.fight_history")
    for module in modules:
        heading = _text(module.select_one("h2, h3, .module_header")) or ""
        if "amateur" in heading.casefold():
            continue
        for row in module.select("table tr"):
            cells = row.select("td")
            if len(cells) < 6:
                continue
            opponent_link = cells[1].select_one('a[href*="/fighter/"]')
            event_link = cells[2].select_one('a[href*="/events/"]')
            opponent_name = _text(opponent_link)
            if not opponent_name:
                continue
            opponent_url = str(opponent_link.get("href")) if opponent_link else None
            event_url = str(event_link.get("href")) if event_link else None
            date_node = cells[2].select_one(".sub_line")
            event_date = _parse_date(_text(date_node))
            method = _text(cells[3])
            method_subline = cells[3].select_one(".sub_line")
            if method_subline:
                referee = _text(method_subline)
                method_subline.extract()
                method = _text(cells[3]) or method
                if referee and method and referee == method:
                    method = None
            if method:
                method = re.sub(r"\s*VIEW PLAY-BY-PLAY\s*$", "", method, flags=re.I).strip() or None
            outcome_node = cells[0].select_one(".final_result") or cells[0]
            outcome = _outcome(_text(outcome_node))
            rows.append({
                "external_bout_id": _external_bout_id(
                    fighter_profile_id,
                    event_url,
                    opponent_url,
                    event_date,
                ),
                "source_url": _absolute_url(event_url) or profile_url,
                "event_name": _text(event_link) or "Event unavailable",
                "event_date": event_date,
                "promotion_name": _promotion_name(_text(event_link)),
                "opponent_name": opponent_name,
                "opponent_url": _absolute_url(opponent_url),
                "opponent_record": None,
                "outcome": outcome,
                "method": method,
                "finish_round": int(_text(cells[4])) if (_text(cells[4]) or "").isdigit() else None,
                "finish_time_seconds": _time_seconds(_text(cells[5])),
                "fight_status": "cancelled" if outcome == "CANCELLED" else "completed",
                "is_title_fight": False,
            })
            if len(rows) >= limit:
                return rows
    return rows


def coverage_without_history(record: str | None) -> tuple[str, str]:
    total = record_total(record)
    if total == 0:
        return (
            "confirmed_debut",
            "Connected record reports 0-0; no prior professional bouts are expected.",
        )
    if total and total > 0:
        return (
            "regional_history_unavailable",
            f"Record {record} indicates prior experience, but bout-by-bout history was not available from connected or fallback sources.",
        )
    return (
        "history_unavailable",
        "No reliable prior-bout listing was found. The fighter may be debuting or coming from a very small regional circuit.",
    )
