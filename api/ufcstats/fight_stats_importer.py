from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fight_stats_scraper import scrape_fight_stats
from uploader import supabase


UFCSTATS_SOURCE_ID = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_external_id(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def find_external_mapping(
    entity_type: str,
    external_id: str,
) -> dict[str, Any] | None:
    response = (
        supabase
        .table("external_ids")
        .select(
            "external_id_map_id, internal_id"
        )
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
            "Fight is not yet imported into Supabase."
        )

    return int(mapping["internal_id"])


def get_fighter_id(
    fighter_external_id: str | None,
) -> int:
    if not fighter_external_id:
        raise RuntimeError(
            "Stat record is missing the fighter's "
            "UFCStats ID."
        )

    mapping = find_external_mapping(
        "fighter",
        fighter_external_id,
    )

    if not mapping:
        raise RuntimeError(
            "Fighter is not yet imported: "
            f"{fighter_external_id}"
        )

    return int(mapping["internal_id"])


def build_database_rows(
    fight_id: int,
    stats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    recorded_at = utc_now()

    for stat in stats:
        fighter_id = get_fighter_id(
            stat.get("fighter_external_id")
        )

        rows.append(
            {
                "fight_id": fight_id,
                "fighter_id": fighter_id,
                "stat_name": stat["stat_name"],
                "stat_value": stat["stat_value"],
                "stat_unit": stat["stat_unit"],
                "round_number": stat["round_number"],
                "source_id": UFCSTATS_SOURCE_ID,
                "recorded_at": recorded_at,
            }
        )

    return rows


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


def import_fight_stats(
    fight_url: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    fight_id = get_fight_id(
        fight_url
    )

    stats = scrape_fight_stats(
        fight_url
    )

    rows = build_database_rows(
        fight_id,
        stats,
    )

    if dry_run:
        print(
            "\nDRY RUN — no database changes"
        )
        print(
            f"Fight ID: {fight_id}"
        )
        print(
            f"Rows prepared: {len(rows)}"
        )

        for row in rows[:10]:
            print(row)

        return {
            "status": "dry_run",
            "fight_id": fight_id,
            "rows": len(rows),
        }

    processed_count = 0

    for chunk in chunk_rows(rows):
        response = (
            supabase
            .table("fight_stats")
            .upsert(
                chunk,
                on_conflict=(
                    "fight_id,"
                    "fighter_id,"
                    "stat_name,"
                    "round_number,"
                    "source_id"
                ),
            )
            .execute()
        )

        if response.data is None:
            raise RuntimeError(
                "Fight-stat upsert returned "
                "no response data."
            )

        processed_count += len(chunk)

    print(
        f"\nUPSERTED {processed_count} "
        f"fight-stat records."
    )

    return {
        "status": "upserted",
        "fight_id": fight_id,
        "rows": processed_count,
    }