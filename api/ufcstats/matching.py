from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalized_name(value: str | None) -> str:
    ascii_value = unicodedata.normalize(
        "NFKD",
        value or "",
    ).encode("ascii", "ignore").decode("ascii")
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        ascii_value.casefold(),
    ).strip()


def parse_height_inches(value: str | None) -> int | None:
    match = re.fullmatch(
        r"\s*(\d+)\s*'\s*(\d+)\s*\"?\s*",
        value or "",
    )
    if not match:
        return None
    return int(match.group(1)) * 12 + int(match.group(2))


def parse_reach_inches(value: str | None) -> int | None:
    match = re.fullmatch(r"\s*(\d+)\s*\"?\s*", value or "")
    return int(match.group(1)) if match else None


def matching_event_id(
    rows: list[dict[str, Any]],
    event_name: str,
) -> int | None:
    exact = [
        row
        for row in rows
        if normalized_name(row.get("event_name"))
        == normalized_name(event_name)
    ]
    if exact:
        return int(exact[0]["event_id"])
    return int(rows[0]["event_id"]) if len(rows) == 1 else None


def matching_fighter_id(
    rows: list[dict[str, Any]],
    fighter_name: str,
) -> int | None:
    matches = [
        row
        for row in rows
        if normalized_name(row.get("full_name"))
        == normalized_name(fighter_name)
    ]
    if len(matches) > 1:
        raise RuntimeError(
            f"Multiple fighters match UFCStats name: {fighter_name}"
        )
    return int(matches[0]["fighter_id"]) if matches else None


def matching_fight_id(
    rows: list[dict[str, Any]],
    fighter_a_id: int,
    fighter_b_id: int,
) -> int | None:
    target = {fighter_a_id, fighter_b_id}
    for row in rows:
        current = {
            int(row["fighter_a_id"]),
            int(row["fighter_b_id"]),
        }
        if current == target:
            return int(row["fight_id"])
    return None
