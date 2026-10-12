from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[2]
UFCSTATS_ROOT = API_ROOT / "ufcstats"
for root in (API_ROOT, UFCSTATS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from uploader import supabase  # noqa: E402
from providers.errors import safe_error
from providers.the_odds_api.import_one_matchup import import_moneylines  # noqa: E402

from .client import FightOddsClient
from .normalizer import match_event, match_fight, parse_event_odds, parse_upcoming_events


SOURCE_NAME = "FightOdds Public Pages"
INACTIVE_STATUSES = {"cancelled", "completed", "draw", "no_contest"}


def _source_id() -> int:
    response = (
        supabase.table("data_sources")
        .select("source_id")
        .eq("name", SOURCE_NAME)
        .limit(1)
        .execute()
    )
    if response.data:
        return int(response.data[0]["source_id"])

    created = supabase.table("data_sources").insert({"name": SOURCE_NAME}).execute()
    if not created.data:
        raise RuntimeError("FightOdds data source could not be registered.")
    return int(created.data[0]["source_id"])


def _database_fights(event_id: int) -> list[dict[str, Any]]:
    response = (
        supabase.table("fights")
        .select(
            "fight_id,event_id,fight_status,"
            "fighter_a:fighters!fights_fighter_a_id_fkey(fighter_id,full_name),"
            "fighter_b:fighters!fights_fighter_b_id_fkey(fighter_id,full_name)"
        )
        .eq("event_id", event_id)
        .execute()
    )
    return [
        fight for fight in (response.data or [])
        if fight.get("fight_status") not in INACTIVE_STATUSES
    ]


def _sportsbook_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _api_shape(
    external_fight: dict[str, Any],
    database_fight: dict[str, Any],
    orientation: str,
    event_date: str,
) -> dict[str, Any]:
    recorded_at = datetime.now(timezone.utc).isoformat()
    fighter_a_name = str((database_fight.get("fighter_a") or {}).get("full_name") or "")
    fighter_b_name = str((database_fight.get("fighter_b") or {}).get("full_name") or "")
    fighter_one_name = fighter_a_name if orientation == "forward" else fighter_b_name
    fighter_two_name = fighter_b_name if orientation == "forward" else fighter_a_name
    bookmakers = []
    for book in external_fight["sportsbooks"]:
        bookmakers.append({
            "title": book["sportsbook"],
            "key": _sportsbook_key(book["sportsbook"]),
            "last_update": recorded_at,
            "markets": [{
                "key": "h2h",
                "last_update": recorded_at,
                "outcomes": [
                    {"name": fighter_one_name, "price": book["fighter_one_odds"]},
                    {"name": fighter_two_name, "price": book["fighter_two_odds"]},
                ],
            }],
        })
    return {
        "home_team": external_fight["fighter_one"],
        "away_team": external_fight["fighter_two"],
        "commence_time": None,
        "bookmakers": bookmakers,
        "event_date": event_date,
    }


def import_fightodds_odds(target_cards: list[dict[str, Any]]) -> dict[str, Any]:
    cards = [
        card for card in target_cards
        if card.get("odds_expected")
        and int(card.get("fights_with_odds") or 0) < int(card.get("fights") or 0)
    ]
    if not cards:
        return {"status": "skipped_no_gaps", "cards_targeted": 0, "requests": 0}

    source_id = _source_id()
    metrics: dict[str, Any] = {
        "status": "completed",
        "cards_targeted": len(cards),
        "cards_matched": 0,
        "external_fights": 0,
        "matched": 0,
        "inserted": 0,
        "unchanged": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "failures": 0,
        "requests": 0,
        "review_sample": [],
    }

    with FightOddsClient() as client:
        external_events = parse_upcoming_events(client.get_upcoming_events())
        for card in cards:
            event_result = match_event(card, external_events)
            if event_result["status"] != "matched":
                metrics[event_result["status"]] = metrics.get(event_result["status"], 0) + 1
                metrics["review_sample"].append({
                    "event": card.get("event_name"),
                    "status": event_result["status"],
                    "reason": event_result["reason"],
                })
                continue

            external_event = event_result["event"]
            try:
                external_fights = parse_event_odds(
                    client.get_event_odds(external_event["odds_url"])
                )
            except Exception as error:
                metrics["failures"] += 1
                metrics["review_sample"].append({
                    "event": card.get("event_name"),
                    "status": "failed",
                    "reason": safe_error(error),
                })
                continue

            if not external_fights:
                metrics["failures"] += 1
                metrics["review_sample"].append({
                    "event": card.get("event_name"),
                    "status": "failed",
                    "reason": (
                        "FightOdds rendered the event page, but no parseable "
                        "fighter moneylines were present."
                    ),
                })
                continue

            metrics["cards_matched"] += 1
            metrics["external_fights"] += len(external_fights)
            database_fights = _database_fights(int(card["event_id"]))
            for external_fight in external_fights:
                fight_result = match_fight(external_fight, database_fights)
                matchup = (
                    f"{external_fight['fighter_one']} vs "
                    f"{external_fight['fighter_two']}"
                )
                if fight_result["status"] != "matched":
                    metrics[fight_result["status"]] += 1
                    if len(metrics["review_sample"]) < 12:
                        metrics["review_sample"].append({
                            "event": card.get("event_name"),
                            "matchup": matchup,
                            "status": fight_result["status"],
                            "reason": fight_result["reason"],
                        })
                    continue

                result = import_moneylines(
                    _api_shape(
                        external_fight,
                        fight_result["fight"],
                        fight_result["orientation"],
                        str(card.get("event_date") or ""),
                    ),
                    fight_result["fight"],
                    source_id,
                )
                metrics["matched"] += 1
                metrics["inserted"] += int(result["inserted"])
                metrics["unchanged"] += int(result["unchanged"])

        metrics["requests"] = client.request_count

    if metrics["failures"]:
        metrics["status"] = "partial"
    return metrics
