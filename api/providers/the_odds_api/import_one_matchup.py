from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from providers.persistence import find_identity, save_entity, lease_arguments, rpc_value
from providers.sportsbooks import sportsbook_key as canonical_book_key

API_ROOT = Path(__file__).resolve().parents[2]
UFCSTATS_ROOT = API_ROOT / "ufcstats"
for root in (API_ROOT, UFCSTATS_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

if "client" in sys.modules and hasattr(sys.modules["client"], "supabase"):
    supabase = sys.modules["client"].supabase
else:
    from uploader import supabase  # noqa: E402

try:
    from .fight_matcher import (
        get_fighter_id_for_selection,
        load_database_fights,
        match_api_fight,
        matchup_key,
    )
except ImportError:
    from fight_matcher import (
        get_fighter_id_for_selection,
        load_database_fights,
        match_api_fight,
        matchup_key,
    )


TARGET_FIGHTERS = (
    "Uros Medic",
    "Daniel Rodriguez",
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def american_to_decimal(
    american_odds: int,
) -> float:
    if american_odds > 0:
        return round(
            1 + american_odds / 100,
            4,
        )

    return round(
        1 + 100 / abs(american_odds),
        4,
    )


def american_to_probability(
    american_odds: int,
) -> float:
    if american_odds > 0:
        probability = (
            100
            / (american_odds + 100)
        )

    else:
        probability = (
            abs(american_odds)
            / (
                abs(american_odds)
                + 100
            )
        )

    return round(
        probability,
        5,
    )


def get_odds_source_id() -> int:
    response = (
        supabase
        .table("data_sources")
        .select("source_id")
        .eq(
            "name",
            "The Odds API",
        )
        .limit(1)
        .execute()
    )

    if not response.data:
        raise RuntimeError(
            "The Odds API is missing from "
            "the data_sources table."
        )

    return int(
        response.data[0]["source_id"]
    )


def find_api_fight(
    api_fights: list[dict[str, Any]],
) -> dict[str, Any]:
    target_key = matchup_key(
        TARGET_FIGHTERS[0],
        TARGET_FIGHTERS[1],
    )

    for api_fight in api_fights:
        current_key = matchup_key(
            api_fight.get(
                "home_team",
                "",
            ),
            api_fight.get(
                "away_team",
                "",
            ),
        )

        if current_key == target_key:
            return api_fight

    raise RuntimeError(
        "The target matchup was not found "
        "in The Odds API response."
    )


def get_existing_external_mapping(
    source_id: int,
    external_id: str,
) -> dict[str, Any] | None:
    return find_identity(supabase,"fight",source_id,external_id)


def create_external_mapping(
    source_id: int,
    fight_id: int,
    external_id: str,
) -> None:
    save_entity(supabase,"fight",{},source_id,external_id,existing_id=fight_id)


def latest_price_matches(
    fight_id: int,
    fighter_id: int,
    sportsbook: str,
    american_odds: int,
    source_id: int,
) -> bool:
    response = (
        supabase
        .table("odds")
        .select("american_odds")
        .eq("fight_id", fight_id)
        .eq("fighter_id", fighter_id)
        .eq("sportsbook", sportsbook)
        .eq("market_type", "moneyline")
        .eq("source_id", source_id)
        .order(
            "recorded_at",
            desc=True,
        )
        .limit(1)
        .execute()
    )

    if not response.data:
        return False

    return (
        int(
            response.data[0][
                "american_odds"
            ]
        )
        == american_odds
    )


def import_moneylines(
    api_fight: dict[str, Any],
    database_fight: dict[str, Any],
    source_id: int,
) -> dict[str, int]:
    inserted = 0
    unchanged = 0
    skipped = 0

    rows = []

    fight_id = int(
        database_fight["fight_id"]
    )

    for bookmaker in api_fight.get(
        "bookmakers",
        [],
    ):
        sportsbook = bookmaker.get(
            "title"
        )
        sportsbook_key = bookmaker.get(
            "key"
        )

        if not sportsbook:
            continue

        for market in bookmaker.get(
            "markets",
            [],
        ):
            if market.get("key") != "h2h":
                continue

            recorded_at = (
                market.get("last_update")
                or bookmaker.get(
                    "last_update"
                )
                or utc_now()
            )

            for outcome in market.get(
                "outcomes",
                [],
            ):
                selection_name = outcome.get(
                    "name"
                )

                price = outcome.get(
                    "price"
                )

                if (
                    not selection_name
                    or price is None
                ):
                    skipped += 1
                    continue

                fighter_id = (
                    get_fighter_id_for_selection(
                        database_fight,
                        selection_name,
                    )
                )

                if fighter_id is None:
                    print(
                        "SKIP — could not match "
                        "outcome to fighter:",
                        selection_name,
                    )

                    skipped += 1
                    continue

                american_odds = int(price)

                rows.append(
                    {
                        "fight_id": fight_id,
                        "fighter_id":
                            fighter_id,
                        "sportsbook":
                            sportsbook,
                        "sportsbook_key":
                            canonical_book_key(sportsbook,sportsbook_key),
                        "market_type":
                            "moneyline",
                        "selection_name":
                            selection_name,
                        "american_odds":
                            american_odds,
                        "decimal_odds":
                            american_to_decimal(
                                american_odds
                            ),
                        "implied_probability":
                            american_to_probability(
                                american_odds
                            ),
                        "source_id":
                            source_id,
                        "provider_updated_at":
                            recorded_at,
                        "market_commence_time":
                            api_fight.get(
                                "commence_time"
                            ),
                    }
                )

    if rows:
        result = rpc_value(supabase.rpc("mma_record_odds", {"p_rows":rows,**lease_arguments()}).execute())
        return {"inserted":result["inserted"],"unchanged":result["unchanged"],"skipped":skipped+result["skipped"]}
    return {"inserted":0,"unchanged":0,"skipped":skipped}


if __name__ == "__main__":
    raise SystemExit("Use npm run sync:odds for the current card window. This helper does not import a hard-coded demonstration matchup.")
