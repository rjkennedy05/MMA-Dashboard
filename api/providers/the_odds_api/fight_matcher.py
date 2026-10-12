from __future__ import annotations

import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2]
UFCSTATS_ROOT = API_ROOT / "ufcstats"
for root in (API_ROOT, UFCSTATS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from uploader import supabase  # noqa: E402


GENERATIONAL_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str | None) -> str:
    """
    Normalize differences such as:

    Uroš Medić
    Uros Medic
    """

    if not name:
        return ""

    without_nickname = re.sub(r'["“][^"”]+["”]', " ", name)

    normalized = unicodedata.normalize(
        "NFKD",
        without_nickname,
    )

    without_accents = "".join(
        character
        for character in normalized
        if not unicodedata.combining(
            character
        )
    )

    lowercase = without_accents.lower()

    alphanumeric = re.sub(
        r"[^a-z0-9]+",
        " ",
        lowercase,
    )

    tokens = alphanumeric.split()
    while tokens and tokens[-1] in GENERATIONAL_SUFFIXES:
        tokens.pop()

    return " ".join(tokens)


def comparison_name(name: str | None) -> str:
    """Collapse token spacing for provider variants such as JooSang/Joo Sang."""
    return normalize_name(name).replace(" ", "")


def matchup_key(
    fighter_one: str,
    fighter_two: str,
) -> tuple[str, str]:
    return tuple(
        sorted(
            [
                comparison_name(
                    fighter_one
                ),
                comparison_name(
                    fighter_two
                ),
            ]
        )
    )


def parse_api_date(
    commence_time: str,
) -> date:
    parsed = datetime.fromisoformat(
        commence_time.replace(
            "Z",
            "+00:00",
        )
    )

    return parsed.astimezone(ZoneInfo("America/Chicago")).date() if parsed.tzinfo else parsed.date()


def load_database_fights(
) -> list[dict[str, Any]]:
    response = (
        supabase
        .table("fights")
        .select(
            """
            fight_id,
            event_id,
            fight_status,
            fighter_a:fighters!fights_fighter_a_id_fkey(
                fighter_id,
                full_name
            ),
            fighter_b:fighters!fights_fighter_b_id_fkey(
                fighter_id,
                full_name
            ),
            events!inner(
                event_id,
                event_name,
                event_date
            )
            """
        )
        .gte("events.event_date",(datetime.now(ZoneInfo("America/Chicago")).date()-timedelta(days=2)).isoformat())
        .lte("events.event_date",(datetime.now(ZoneInfo("America/Chicago")).date()+timedelta(days=90)).isoformat())
        .execute()
    )

    return [row for row in (response.data or []) if row.get("fight_status") not in {"cancelled","completed","draw","no_contest"}]


def match_api_fight(
    api_fight: dict[str, Any],
    database_fights: list[
        dict[str, Any]
    ],
    date_tolerance_days: int = 1,
) -> dict[str, Any]:
    api_key = matchup_key(
        api_fight["home_team"],
        api_fight["away_team"],
    )

    api_date = parse_api_date(
        api_fight["commence_time"]
    )

    candidates = []
    name_matches = []

    for database_fight in database_fights:
        fighter_a = (
            database_fight.get(
                "fighter_a"
            )
            or {}
        )

        fighter_b = (
            database_fight.get(
                "fighter_b"
            )
            or {}
        )

        event = (
            database_fight.get("events")
            or {}
        )

        event_date_text = event.get(
            "event_date"
        )

        if not event_date_text:
            continue

        database_key = matchup_key(
            fighter_a.get(
                "full_name",
                "",
            ),
            fighter_b.get(
                "full_name",
                "",
            ),
        )

        if database_key != api_key:
            continue

        database_date = date.fromisoformat(
            event_date_text
        )

        difference = abs(
            (
                database_date
                - api_date
            ).days
        )

        name_matches.append(
            {
                "fight": database_fight,
                "date_difference": difference,
                "event_date": database_date.isoformat(),
            }
        )

        if difference <= date_tolerance_days:
            candidates.append(
                {
                    "fight": database_fight,
                    "date_difference":
                        difference,
                }
            )

    if not candidates:
        if name_matches:
            closest = min(name_matches, key=lambda candidate: candidate["date_difference"])
            return {
                "status": "unmatched",
                "reason": (
                    "Fighter names matched, but the closest stored event date "
                    f"was {closest['date_difference']} days away "
                    f"({closest['event_date']})."
                ),
                "name_match_fight_id": closest["fight"].get("fight_id"),
            }
        return {
            "status": "unmatched",
            "reason": (
                "No existing Supabase fight "
                "matched the fighter names "
                "and date."
            ),
        }

    candidates.sort(
        key=lambda candidate:
            candidate[
                "date_difference"
            ]
    )

    best_difference = candidates[0][
        "date_difference"
    ]

    best_candidates = [
        candidate
        for candidate in candidates
        if candidate[
            "date_difference"
        ] == best_difference
    ]

    if len(best_candidates) > 1:
        return {
            "status": "ambiguous",
            "reason": (
                "Multiple Supabase fights "
                "matched this matchup."
            ),
            "candidates": [
                candidate["fight"][
                    "fight_id"
                ]
                for candidate
                in best_candidates
            ],
        }

    return {
        "status": "matched",
        "fight":
            best_candidates[0][
                "fight"
            ],
    }


def get_fighter_id_for_selection(
    database_fight: dict[str, Any],
    selection_name: str,
) -> int | None:
    selection = comparison_name(
        selection_name
    )

    fighter_a = (
        database_fight.get(
            "fighter_a"
        )
        or {}
    )

    fighter_b = (
        database_fight.get(
            "fighter_b"
        )
        or {}
    )

    if selection == comparison_name(
        fighter_a.get("full_name")
    ):
        return int(
            fighter_a["fighter_id"]
        )

    if selection == comparison_name(
        fighter_b.get("full_name")
    ):
        return int(
            fighter_b["fighter_id"]
        )

    return None
