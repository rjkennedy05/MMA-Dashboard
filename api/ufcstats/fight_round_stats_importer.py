from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fight_stats_scraper import scrape_fight_stats
from uploader import supabase


UFCSTATS_SOURCE_ID = 1


STAT_COLUMNS = {
    "knockdowns",
    "significant_strikes_landed",
    "significant_strikes_attempted",
    "total_strikes_landed",
    "total_strikes_attempted",
    "takedowns_landed",
    "takedowns_attempted",
    "submission_attempts",
    "reversals",
    "control_time_seconds",
    "significant_head_strikes_landed",
    "significant_head_strikes_attempted",
    "significant_body_strikes_landed",
    "significant_body_strikes_attempted",
    "significant_leg_strikes_landed",
    "significant_leg_strikes_attempted",
    "significant_distance_strikes_landed",
    "significant_distance_strikes_attempted",
    "significant_clinch_strikes_landed",
    "significant_clinch_strikes_attempted",
    "significant_ground_strikes_landed",
    "significant_ground_strikes_attempted",
}


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def get_external_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def find_external_mapping(
    entity_type: str,
    external_id: str,
) -> dict[str, Any] | None:
    response = (
        supabase
        .table("external_ids")
        .select("internal_id")
        .eq("entity_type", entity_type)
        .eq("source_id", UFCSTATS_SOURCE_ID)
        .eq("external_id", external_id)
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def get_fight_id(fight_url: str) -> int:
    mapping = find_external_mapping(
        "fight",
        get_external_id(fight_url),
    )

    if not mapping:
        raise RuntimeError(
            "Fight is not imported into Supabase. "
            f"Missing fight mapping for {fight_url}"
        )

    return int(mapping["internal_id"])


def get_fighter_id(
    fighter_external_id: str | None,
) -> int:
    if not fighter_external_id:
        raise RuntimeError(
            "A stat record is missing its "
            "UFCStats fighter ID."
        )

    mapping = find_external_mapping(
        "fighter",
        fighter_external_id,
    )

    if not mapping:
        raise RuntimeError(
            "Fighter is not imported into Supabase: "
            f"{fighter_external_id}"
        )

    return int(mapping["internal_id"])


def create_empty_round_row(
    fight_id: int,
    fighter_id: int,
    round_number: int,
    recorded_at: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "fight_id": fight_id,
        "fighter_id": fighter_id,
        "round_number": round_number,
        "source_id": UFCSTATS_SOURCE_ID,
        "recorded_at": recorded_at,
        "updated_at": recorded_at,
        "extra_stats": {},
    }

    # Null means unavailable.
    # Zero means the stat was recorded as zero.
    for column in STAT_COLUMNS:
        row[column] = None

    return row


def build_round_rows(
    fight_id: int,
    stats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    recorded_at = utc_now()

    grouped_rows: dict[
        tuple[int, int],
        dict[str, Any],
    ] = {}

    for stat in stats:
        fighter_id = get_fighter_id(
            stat.get("fighter_external_id")
        )

        round_number = int(
            stat["round_number"]
        )

        key = (
            fighter_id,
            round_number,
        )

        if key not in grouped_rows:
            grouped_rows[key] = (
                create_empty_round_row(
                    fight_id=fight_id,
                    fighter_id=fighter_id,
                    round_number=round_number,
                    recorded_at=recorded_at,
                )
            )

        stat_name = stat["stat_name"]
        stat_value = stat["stat_value"]

        if stat_name in STAT_COLUMNS:
            grouped_rows[key][stat_name] = (
                stat_value
            )
        else:
            grouped_rows[key][
                "extra_stats"
            ][stat_name] = stat_value

    return list(grouped_rows.values())


def chunk_rows(
    rows: list[dict[str, Any]],
    chunk_size: int = 100,
):
    for start in range(
        0,
        len(rows),
        chunk_size,
    ):
        yield rows[
            start:start + chunk_size
        ]


def import_fight_round_stats(
    fight_url: str,
    dry_run: bool = False,
    normalized_stats: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fight_id = get_fight_id(
        fight_url
    )

    if normalized_stats is None:
        normalized_stats = scrape_fight_stats(
            fight_url
        )

    rows = build_round_rows(
        fight_id,
        normalized_stats,
    )

    if dry_run:
        print(
            "\nDRY RUN — no database changes"
        )
        print(
            f"Normalized source records: "
            f"{len(normalized_stats)}"
        )
        print(
            f"Compact round rows: "
            f"{len(rows)}"
        )

        for row in rows[:3]:
            print(row)

        return {
            "status": "dry_run",
            "fight_id": fight_id,
            "source_records":
                len(normalized_stats),
            "round_rows": len(rows),
        }

    processed_count = 0

    for chunk in chunk_rows(rows):
        response = (
            supabase
            .table("fight_round_stats")
            .upsert(
                chunk,
                on_conflict=(
                    "fight_id,"
                    "fighter_id,"
                    "round_number,"
                    "source_id"
                ),
            )
            .execute()
        )

        if response.data is None:
            raise RuntimeError(
                "Round-stat upsert returned "
                "no response data."
            )

        processed_count += len(chunk)

    print(
        f"\nUPSERTED {processed_count} "
        "compact round-stat rows."
    )

    return {
        "status": "upserted",
        "fight_id": fight_id,
        "source_records":
            len(normalized_stats),
        "round_rows": processed_count,
    }
