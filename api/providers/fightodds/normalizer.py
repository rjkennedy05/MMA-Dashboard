from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin


BASE_URL = "https://fightodds.io"
EVENT_PATTERN = re.compile(r"^/mma-events/(\d+)/([^?#]+)")
FIGHTER_PATTERN = re.compile(r"^/fighters/")
AMERICAN_PRICE_PATTERN = re.compile(r"(?:^|\s)([+-]\d{2,5})(?:\s|$)")
GENERATIONAL_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalized_text(value: str | None) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_accents.lower()).split())


def normalized_name(value: str | None) -> str:
    tokens = normalized_text(value).split()
    while tokens and tokens[-1] in GENERATIONAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def compact_name(value: str | None) -> str:
    return normalized_name(value).replace(" ", "")


def name_similarity(first: str | None, second: str | None) -> float:
    first_normalized = normalized_name(first)
    second_normalized = normalized_name(second)
    first_compact = first_normalized.replace(" ", "")
    second_compact = second_normalized.replace(" ", "")

    if not first_compact or not second_compact:
        return 0.0
    if first_compact == second_compact:
        return 1.0
    if (
        min(len(first_compact), len(second_compact)) >= 4
        and (first_compact in second_compact or second_compact in first_compact)
    ):
        return 0.93

    first_tokens = first_normalized.split()
    second_tokens = second_normalized.split()
    if len(first_tokens) == len(second_tokens) and len(first_tokens) >= 2:
        remaining = list(second_tokens)
        token_scores = []
        for token in sorted(first_tokens, key=len, reverse=True):
            best_index = max(
                range(len(remaining)),
                key=lambda index: SequenceMatcher(
                    None,
                    token,
                    remaining[index],
                ).ratio(),
            )
            best_score = SequenceMatcher(
                None,
                token,
                remaining[best_index],
            ).ratio()
            token_scores.append(best_score)
            remaining.pop(best_index)
        if token_scores and min(token_scores) >= 0.82:
            return max(0.92, sum(token_scores) / len(token_scores))

    sequence_score = SequenceMatcher(None, first_compact, second_compact).ratio()
    if (
        first_tokens
        and second_tokens
        and len(first_tokens[0]) >= 5
        and first_tokens[0] == second_tokens[0]
    ):
        return max(0.84, sequence_score)
    return sequence_score


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._href is not None:
            return
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        if EVENT_PATTERN.match(href):
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            title = " ".join("".join(self._text).split())
            if title:
                self.links.append({"href": self._href, "title": title})
            self._href = None
            self._text = []


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._table: list[list[dict[str, Any]]] | None = None
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None
        self._table_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            if self._table is None:
                self._table = []
                self._table_depth = 1
            else:
                self._table_depth += 1
            return
        if self._table is None:
            return
        if tag == "tr" and self._row is None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None and self._cell is None:
            self._cell = {"text": [], "links": []}
        elif tag == "a" and self._cell is not None:
            href = attributes.get("href")
            if href:
                self._cell["links"].append(href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._table is None:
            return
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._cell["text"] = " ".join("".join(self._cell["text"]).split())
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            self._table_depth -= 1
            if self._table_depth == 0:
                self.tables.append(self._table)
                self._table = None


def parse_upcoming_events(html: str) -> list[dict[str, str]]:
    parser = _LinkParser()
    parser.feed(html)
    events: list[dict[str, str]] = []
    seen: set[str] = set()
    for link in parser.links:
        match = EVENT_PATTERN.match(link["href"])
        if not match or match.group(1) in seen:
            continue
        event_id, slug = match.groups()
        seen.add(event_id)
        events.append({
            "external_id": event_id,
            "event_name": link["title"],
            "event_url": urljoin(BASE_URL, link["href"]),
            "odds_url": f"{BASE_URL}/odds/{event_id}/{slug}?bot=true",
        })
    return events


def _price(cell_text: str) -> int | None:
    match = AMERICAN_PRICE_PATTERN.search(cell_text)
    return int(match.group(1)) if match else None


def parse_event_odds(html: str) -> list[dict[str, Any]]:
    parser = _TableParser()
    parser.feed(html)
    odds_table = next(
        (
            table for table in parser.tables
            if table and table[0]
            and normalized_text(table[0][0]["text"]) == "fighters"
        ),
        None,
    )
    if not odds_table:
        return []

    headers = [cell["text"] for cell in odds_table[0]]
    fighter_rows: list[dict[str, Any]] = []
    for row in odds_table[1:]:
        if not row or not any(FIGHTER_PATTERN.match(href) for href in row[0]["links"]):
            continue
        prices: dict[str, int] = {}
        for index, cell in enumerate(row[1:], start=1):
            if index >= len(headers) or not headers[index]:
                continue
            price = _price(cell["text"])
            if price is not None:
                prices[headers[index]] = price
        fighter_rows.append({"fighter": row[0]["text"], "prices": prices})

    fights: list[dict[str, Any]] = []
    for index in range(0, len(fighter_rows) - 1, 2):
        first = fighter_rows[index]
        second = fighter_rows[index + 1]
        books = []
        for sportsbook in sorted(set(first["prices"]) & set(second["prices"])):
            books.append({
                "sportsbook": sportsbook,
                "fighter_one_odds": first["prices"][sportsbook],
                "fighter_two_odds": second["prices"][sportsbook],
            })
        if books:
            fights.append({
                "fighter_one": first["fighter"],
                "fighter_two": second["fighter"],
                "sportsbooks": books,
            })
    return fights


def event_match_score(dashboard_name: str, external_name: str) -> float:
    dashboard = normalized_text(dashboard_name)
    external = normalized_text(external_name)
    if not dashboard or not external:
        return 0.0
    if dashboard == external:
        return 1.0

    dashboard_numbers = set(re.findall(r"\d+", dashboard))
    external_numbers = set(re.findall(r"\d+", external))
    if dashboard_numbers and external_numbers and not dashboard_numbers.intersection(external_numbers):
        return 0.0
    if min(len(dashboard), len(external)) >= 8 and (dashboard in external or external in dashboard):
        return 0.95

    dashboard_tokens = set(dashboard.split())
    external_tokens = set(external.split())
    token_score = len(dashboard_tokens & external_tokens) / max(
        1, len(dashboard_tokens | external_tokens)
    )
    sequence_score = SequenceMatcher(None, dashboard, external).ratio()
    return max(token_score, sequence_score)


def match_event(
    dashboard_event: dict[str, Any],
    external_events: list[dict[str, str]],
) -> dict[str, Any]:
    ranked = sorted(
        (
            (event_match_score(str(dashboard_event.get("event_name") or ""), event["event_name"]), event)
            for event in external_events
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.72:
        return {"status": "unmatched", "reason": "No FightOdds event title matched safely."}
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.03:
        return {"status": "ambiguous", "reason": "Multiple FightOdds events matched the card title."}
    return {"status": "matched", "event": ranked[0][1], "score": ranked[0][0]}


def _fighter_name(fight: dict[str, Any], side: str) -> str:
    value = fight.get(side) or {}
    return str(value.get("full_name") or value.get("name") or "")


def match_fight(
    external_fight: dict[str, Any],
    database_fights: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = []
    for fight in database_fights:
        fighter_a = _fighter_name(fight, "fighter_a")
        fighter_b = _fighter_name(fight, "fighter_b")
        forward = (
            name_similarity(external_fight["fighter_one"], fighter_a),
            name_similarity(external_fight["fighter_two"], fighter_b),
        )
        reverse = (
            name_similarity(external_fight["fighter_one"], fighter_b),
            name_similarity(external_fight["fighter_two"], fighter_a),
        )
        forward_orientation = sum(forward) >= sum(reverse)
        scores = forward if forward_orientation else reverse
        average = sum(scores) / 2
        if min(scores) >= 0.60 and average >= 0.76:
            candidates.append({
                "fight": fight,
                "score": average,
                "side_scores": scores,
                "orientation": "forward" if forward_orientation else "reverse",
            })

    candidates.sort(key=lambda candidate: candidate["score"], reverse=True)
    if not candidates:
        return {"status": "unmatched", "reason": "No same-card fighter pair matched safely."}
    if len(candidates) > 1 and candidates[0]["score"] - candidates[1]["score"] < 0.03:
        return {"status": "ambiguous", "reason": "Multiple same-card fights matched similarly."}
    return {"status": "matched", **candidates[0]}
