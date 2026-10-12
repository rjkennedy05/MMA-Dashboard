from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .client import get_current_mma_moneylines
    from .fight_matcher import load_database_fights, match_api_fight
    from .import_one_matchup import (
        create_external_mapping,
        get_existing_external_mapping,
        get_odds_source_id,
        import_moneylines,
    )
except ImportError:
    from client import get_current_mma_moneylines
    from fight_matcher import load_database_fights, match_api_fight
    from import_one_matchup import (
        create_external_mapping,
        get_existing_external_mapping,
        get_odds_source_id,
        import_moneylines,
    )


from providers.errors import safe_error

def configure_utf8_console() -> None:
    """Keep fighter names Unicode-safe in Windows consoles and task pipes."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


configure_utf8_console()


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def bookmaker_count(
    api_fight: dict[str, Any],
) -> int:
    return len(
        api_fight.get("bookmakers", [])
    )


def find_database_fight(
    database_fights: list[dict[str, Any]],
    fight_id: int,
) -> dict[str, Any] | None:
    return next(
        (
            fight
            for fight in database_fights
            if int(fight["fight_id"])
            == fight_id
        ),
        None,
    )


def build_review_record(
    api_fight: dict[str, Any],
    status: str,
    reason: str,
    candidates: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "odds_api_id":
            api_fight.get("id"),

        "commence_time":
            api_fight.get(
                "commence_time"
            ),

        "home_team":
            api_fight.get("home_team"),

        "away_team":
            api_fight.get("away_team"),

        "bookmaker_count":
            bookmaker_count(api_fight),

        "status":
            status,

        "reason":
            reason,

        "candidate_fight_ids":
            candidates or [],
    }


def write_review_report(
    records: list[dict[str, Any]],
) -> Path | None:
    if not records:
        return None

    report_directory = (
        Path(__file__).resolve().parent
        / "reports"
    )

    report_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = utc_now().strftime(
        "%Y%m%dT%H%M%SZ"
    )

    report_path = (
        report_directory
        / (
            "unmatched_odds_"
            f"{timestamp}.json"
        )
    )

    report_path.write_text(
        json.dumps(
            records,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return report_path


if __name__ == "__main__":
    api_fights, usage = (
        get_current_mma_moneylines()
    )

    database_fights = (
        load_database_fights()
    )

    source_id = get_odds_source_id()

    matched_count = 0
    existing_mapping_count = 0
    new_mapping_count = 0

    inserted_odds_count = 0
    unchanged_odds_count = 0
    skipped_outcomes_count = 0

    unmatched_count = 0
    ambiguous_count = 0
    failed_count = 0

    review_records = []

    print(
        f"\nOdds API matchups: "
        f"{len(api_fights)}"
    )

    print(
        f"Supabase fights available: "
        f"{len(database_fights)}\n"
    )

    for index, api_fight in enumerate(
        api_fights,
        start=1,
    ):
        matchup = (
            f"{api_fight.get('home_team')} "
            "vs "
            f"{api_fight.get('away_team')}"
        )

        print(
            f"[{index}/{len(api_fights)}] "
            f"{matchup}"
        )

        odds_api_id = api_fight.get("id")

        if not odds_api_id:
            failed_count += 1

            review_records.append(
                build_review_record(
                    api_fight,
                    status="failed",
                    reason=(
                        "The Odds API matchup "
                        "has no ID."
                    ),
                )
            )

            print(
                "  FAILED — missing "
                "Odds API ID"
            )

            continue

        try:
            existing_mapping = (
                get_existing_external_mapping(
                    source_id,
                    odds_api_id,
                )
            )

            database_fight = None

            if existing_mapping:
                fight_id = int(
                    existing_mapping[
                        "internal_id"
                    ]
                )

                database_fight = (
                    find_database_fight(
                        database_fights,
                        fight_id,
                    )
                )

                if not database_fight:
                    raise RuntimeError(
                        "External mapping points "
                        "to a missing fight."
                    )

                existing_mapping_count += 1

            else:
                match_result = (
                    match_api_fight(
                        api_fight,
                        database_fights,
                    )
                )

                match_status = (
                    match_result["status"]
                )

                if match_status == "unmatched":
                    unmatched_count += 1

                    review_records.append(
                        build_review_record(
                            api_fight,
                            status="unmatched",
                            reason=match_result[
                                "reason"
                            ],
                        )
                    )

                    print(
                        "  REVIEW — no "
                        "Supabase match"
                    )

                    continue

                if match_status == "ambiguous":
                    ambiguous_count += 1

                    review_records.append(
                        build_review_record(
                            api_fight,
                            status="ambiguous",
                            reason=match_result[
                                "reason"
                            ],
                            candidates=(
                                match_result.get(
                                    "candidates"
                                )
                            ),
                        )
                    )

                    print(
                        "  REVIEW — ambiguous "
                        "Supabase match"
                    )

                    continue

                database_fight = (
                    match_result["fight"]
                )

                fight_id = int(
                    database_fight[
                        "fight_id"
                    ]
                )

                create_external_mapping(
                    source_id,
                    fight_id,
                    odds_api_id,
                )

                new_mapping_count += 1

            matched_count += 1

            result = import_moneylines(
                api_fight,
                database_fight,
                source_id,
            )

            inserted_odds_count += int(
                result["inserted"]
            )

            unchanged_odds_count += int(
                result["unchanged"]
            )

            skipped_outcomes_count += int(
                result["skipped"]
            )

            print(
                "  MATCHED — "
                f"inserted {result['inserted']}, "
                f"unchanged "
                f"{result['unchanged']}, "
                f"skipped {result['skipped']}"
            )

        except Exception as error:
            failed_count += 1

            review_records.append(
                build_review_record(
                    api_fight,
                    status="failed",
                    reason=safe_error(error),
                )
            )

            print(
                "  FAILED:",
                safe_error(error),
            )

    report_path = write_review_report(
        review_records
    )

    print("\n" + "=" * 55)
    print("CURRENT MMA ODDS IMPORT COMPLETE")
    print(f"API matchups reviewed: {len(api_fights)}")
    print(f"Matched to Supabase:   {matched_count}")
    print(
        f"Existing mappings:     "
        f"{existing_mapping_count}"
    )
    print(
        f"New mappings:          "
        f"{new_mapping_count}"
    )
    print(
        f"Odds rows inserted:    "
        f"{inserted_odds_count}"
    )
    print(
        f"Unchanged prices:      "
        f"{unchanged_odds_count}"
    )
    print(
        f"Skipped outcomes:      "
        f"{skipped_outcomes_count}"
    )
    print(f"Unmatched API listings:{unmatched_count:>7}")
    print(f"Ambiguous fights:      {ambiguous_count}")
    print(f"Failures:              {failed_count}")

    if report_path:
        print(
            "Review report:         "
            f"{report_path}"
        )
    else:
        print(
            "Review report:         "
            "None needed"
        )

    print("\nAPI usage:")
    print(f"Regions queried:  {usage['regions']}")
    print(f"Last request cost: {usage['last']}")
    print(f"Credits used:      {usage['used']}")
    print(
        f"Credits remaining: "
        f"{usage['remaining']}"
    )
    print("=" * 55)

    machine_summary = {
        "status": "partial" if failed_count else "completed",
        "api_matchups": len(api_fights),
        "matched": matched_count,
        "inserted": inserted_odds_count,
        "unchanged": unchanged_odds_count,
        "unmatched": unmatched_count,
        "unmatched_label": "API listings with no corresponding dashboard fight",
        "ambiguous": ambiguous_count,
        "failures": failed_count,
        "usage": usage,
        "review_sample": [
            {
                "matchup": (
                    f"{record.get('home_team')} vs {record.get('away_team')}"
                ),
                "status": record.get("status"),
                "reason": record.get("reason"),
            }
            for record in review_records[:12]
        ],
    }
    print("ODDS_IMPORT_SUMMARY=" + json.dumps(machine_summary, ensure_ascii=False))

    if failed_count:
        sys.exit(1)
