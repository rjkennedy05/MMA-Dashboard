from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fighter_importer import import_fighter
from fight_detail_scraper import scrape_fight_detail
from matching import matching_fight_id
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
        .eq(
            "entity_type",
            entity_type,
        )
        .eq(
            "source_id",
            UFCSTATS_SOURCE_ID,
        )
        .eq(
            "external_id",
            external_id,
        )
        .execute()
    )

    if response.data:
        return response.data[0]

    return None


def get_event_id(event_url: str) -> int:
    external_id = get_external_id(
        event_url
    )

    mapping = find_external_mapping(
        "event",
        external_id,
    )

    if not mapping:
        raise RuntimeError(
            "The event has not been imported yet. "
            f"Missing UFCStats event ID: {external_id}"
        )

    return int(mapping["internal_id"])


def find_existing_fight(
    event_id: int,
    fighter_a_id: int,
    fighter_b_id: int,
) -> int | None:
    response = (
        supabase
        .table("fights")
        .select("fight_id, fighter_a_id, fighter_b_id")
        .eq("event_id", event_id)
        .execute()
    )
    return matching_fight_id(
        response.data or [],
        fighter_a_id,
        fighter_b_id,
    )


def attach_fight_mapping(
    fight_id: int,
    external_id: str,
    fight_url: str,
) -> None:
    supabase.table("external_ids").insert(
        {
            "entity_type": "fight",
            "internal_id": fight_id,
            "source_id": UFCSTATS_SOURCE_ID,
            "external_id": external_id,
            "external_url": fight_url,
            "updated_at": utc_now(),
        }
    ).execute()


def get_or_import_fighter(
    fighter_name: str,
    fighter_url: str,
) -> int:
    external_id = get_external_id(
        fighter_url
    )

    mapping = find_external_mapping(
        "fighter",
        external_id,
    )

    if mapping:
        return int(mapping["internal_id"])

    return int(
        import_fighter(
            fighter_name,
            fighter_url,
        )
    )


@lru_cache(maxsize=1)
def load_weight_classes() -> list[dict[str, Any]]:
    response = (
        supabase
        .table("weight_classes")
        .select(
            "weight_class_id, name, gender"
        )
        .execute()
    )

    return response.data or []


def normalize_weight_class(
    raw_name: str | None,
) -> tuple[str | None, str]:
    """
    Examples:

    Lightweight
        -> Lightweight, Men

    Women's Strawweight
        -> Strawweight, Women
    """

    if not raw_name:
        return None, "Men"

    normalized = (
        " ".join(raw_name.split())
        .replace("’", "'")
        .strip()
    )

    lower_name = normalized.lower()

    gender = "Men"

    women_prefixes = (
        "women's ",
        "womens ",
        "women ",
    )

    for prefix in women_prefixes:
        if lower_name.startswith(prefix):
            gender = "Women"
            normalized = normalized[
                len(prefix):
            ].strip()
            break

    return normalized, gender


def get_weight_class_id(
    raw_name: str | None,
) -> int | None:
    name, gender = normalize_weight_class(
        raw_name
    )

    if not name:
        return None

    for weight_class in load_weight_classes():
        database_name = (
            weight_class["name"]
            .strip()
            .lower()
        )

        database_gender = (
            weight_class["gender"]
            .strip()
            .lower()
        )

        if (
            database_name == name.lower()
            and database_gender == gender.lower()
        ):
            return int(
                weight_class[
                    "weight_class_id"
                ]
            )

    print(
        "WARNING — no weight-class mapping:",
        raw_name,
    )

    return None


def build_fight_data(
    event_id: int,
    fight: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    fighter_a_id = get_or_import_fighter(
        fight["fighter_a_name"],
        fight["fighter_a_url"],
    )

    fighter_b_id = get_or_import_fighter(
        fight["fighter_b_name"],
        fight["fighter_b_url"],
    )

    winner_id = None

    winner_external_id = detail.get(
        "winner_external_id"
    )

    if winner_external_id:
        winner_mapping = find_external_mapping(
            "fighter",
            winner_external_id,
        )

        if winner_mapping:
            winner_id = int(
                winner_mapping["internal_id"]
            )

    return {
        "event_id":
            event_id,

        "fighter_a_id":
            fighter_a_id,

        "fighter_b_id":
            fighter_b_id,

        "weight_class_id":
            get_weight_class_id(
                fight.get("weight_class")
            ),

        "scheduled_rounds":
            detail.get("scheduled_rounds"),

        "fight_order":
            fight.get("fight_order"),

        "fight_status":
            detail.get(
                "fight_status",
                "unknown",
            ),

        "winner_id":
            winner_id,

        "result_type":
            detail.get("result_type"),

        "method":
            detail.get("method"),

        "finish_round":
            detail.get("finish_round"),

        "finish_time_seconds":
            detail.get(
                "finish_time_seconds"
            ),

        "is_title_fight":
            bool(
                detail.get("is_title_fight")
            ),

        "updated_at":
            utc_now(),
    }


def import_fight(
    event_url: str,
    fight: dict[str, Any],
    dry_run: bool = False,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fight_url = fight.get("fight_url")

    if not fight_url:
        raise ValueError(
            "Fight URL is missing."
        )

    event_id = get_event_id(
        event_url
    )

    if detail is None:
        detail = scrape_fight_detail(
            fight_url
        )

    fight_data = build_fight_data(
        event_id,
        fight,
        detail,
    )

    external_id = get_external_id(
        fight_url
    )

    existing = find_external_mapping(
        "fight",
        external_id,
    )

    if dry_run:
        print(
            "\nDRY RUN — no database changes"
        )
        print(fight_data)

        return {
            "status": "dry_run",
            "fight_id": (
                existing["internal_id"]
                if existing
                else None
            ),
            "fight_status": detail.get("fight_status"),
            "winner_id": fight_data.get("winner_id"),
        }

    if existing:
        fight_id = int(
            existing["internal_id"]
        )

        response = (
            supabase
            .table("fights")
            .update(fight_data)
            .eq(
                "fight_id",
                fight_id,
            )
            .execute()
        )

        if not response.data:
            raise RuntimeError(
                "Fight update returned no data."
            )

        (
            supabase
            .table("external_ids")
            .update(
                {
                    "external_url":
                        fight_url,

                    "updated_at":
                        utc_now(),
                }
            )
            .eq(
                "external_id_map_id",
                existing[
                    "external_id_map_id"
                ],
            )
            .execute()
        )

        print(
            "UPDATED:",
            fight["fighter_a_name"],
            "vs",
            fight["fighter_b_name"],
        )

        return {
            "status": "updated",
            "fight_id": fight_id,
            "fight_status": detail.get("fight_status"),
            "winner_id": fight_data.get("winner_id"),
        }

    existing_fight_id = find_existing_fight(
        event_id,
        int(fight_data["fighter_a_id"]),
        int(fight_data["fighter_b_id"]),
    )
    if existing_fight_id is not None:
        response = (
            supabase
            .table("fights")
            .update(fight_data)
            .eq("fight_id", existing_fight_id)
            .execute()
        )
        if not response.data:
            raise RuntimeError(
                "Existing fight attachment update returned no data."
            )
        attach_fight_mapping(
            existing_fight_id,
            external_id,
            fight_url,
        )
        print(
            "ATTACHED UFCSTATS:",
            fight["fighter_a_name"],
            "vs",
            fight["fighter_b_name"],
        )
        return {
            "status": "updated",
            "fight_id": existing_fight_id,
            "fight_status": detail.get("fight_status"),
            "winner_id": fight_data.get("winner_id"),
        }

    inserted = (
        supabase
        .table("fights")
        .insert(fight_data)
        .execute()
    )

    if not inserted.data:
        raise RuntimeError(
            "Fight insert returned no data."
        )

    fight_id = int(
        inserted.data[0]["fight_id"]
    )

    try:
        attach_fight_mapping(
            fight_id,
            external_id,
            fight_url,
        )

    except Exception:
        # Avoid leaving a fight without its
        # external-ID mapping.
        (
            supabase
            .table("fights")
            .delete()
            .eq(
                "fight_id",
                fight_id,
            )
            .execute()
        )

        raise

    print(
        "IMPORTED:",
        fight["fighter_a_name"],
        "vs",
        fight["fighter_b_name"],
    )

    return {
        "status": "imported",
        "fight_id": fight_id,
        "fight_status": detail.get("fight_status"),
        "winner_id": fight_data.get("winner_id"),
    }
