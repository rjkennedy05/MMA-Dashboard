import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from matching import matching_event_id


# ==========================================
# Environment and Supabase setup
# ==========================================

ENV_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        ".env",
    )
)

load_dotenv(ENV_PATH)


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv(
    "SUPABASE_SERVICE_KEY"
)


if not SUPABASE_URL:
    raise ValueError(
        "SUPABASE_URL is missing from api/.env"
    )


if not SUPABASE_SERVICE_KEY:
    raise ValueError(
        "SUPABASE_SERVICE_KEY is missing "
        "from api/.env"
    )


supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
)


UFC_PROMOTION_ID = 1
DWCS_PROMOTION_ID = 2
UFCSTATS_SOURCE_ID = 1


# ==========================================
# Utility functions
# ==========================================

def utc_now():
    """Return the current UTC timestamp."""

    return datetime.now(
        timezone.utc
    ).isoformat()


def get_ufcstats_event_id(url):
    """
    Extract the stable ID from a UFCStats URL.

    Example:
    http://ufcstats.com/event-details/abc123

    Returns:
    abc123
    """

    if not url:
        raise ValueError(
            "UFCStats event URL is missing."
        )

    return url.rstrip("/").split("/")[-1]


def parse_location(location):
    """
    Convert a UFCStats location string into
    city, state/region, and country fields.

    Example:
    Las Vegas, NV, United States
    """

    if not location:
        return {
            "city": None,
            "state_region": None,
            "country": None,
        }

    parts = [
        part.strip()
        for part in location.split(",")
        if part.strip()
    ]

    if len(parts) >= 3:
        return {
            "city": parts[0],
            "state_region": parts[1],
            "country": ", ".join(parts[2:]),
        }

    if len(parts) == 2:
        return {
            "city": parts[0],
            "state_region": None,
            "country": parts[1],
        }

    return {
        "city": parts[0] if parts else None,
        "state_region": None,
        "country": None,
    }


# ==========================================
# Database lookup and preparation
# ==========================================

def event_exists(external_id):
    """
    Check whether a UFCStats event has
    already been imported.
    """

    response = (
        supabase
        .table("external_ids")
        .select(
            "external_id_map_id, internal_id"
        )
        .eq(
            "entity_type",
            "event",
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


def find_existing_event(event_data):
    """Reuse a schedule/manual row before creating a UFCStats duplicate."""
    event_date = event_data.get("event_date")
    promotion_id = event_data.get("promotion_id")
    event_name = event_data.get("event_name")

    if not event_date or not promotion_id or not event_name:
        return None

    response = (
        supabase
        .table("events")
        .select("event_id, event_name")
        .eq("promotion_id", promotion_id)
        .eq("event_date", event_date)
        .execute()
    )
    rows = response.data or []
    return matching_event_id(rows, event_name)


def attach_event_mapping(event_id, external_id, event_url):
    supabase.table("external_ids").insert(
        {
            "entity_type": "event",
            "internal_id": event_id,
            "source_id": UFCSTATS_SOURCE_ID,
            "external_id": external_id,
            "external_url": event_url,
            "updated_at": utc_now(),
        }
    ).execute()


def prepare_event(event):
    """
    Convert scraped UFCStats event data into
    the format expected by the events table.
    """

    if not event.get("name"):
        raise ValueError(
            "Event name is missing."
        )

    location = parse_location(
        event.get("location")
    )

    normalized_event_name = (
        event["name"]
        .lower()
        .replace("’", "'")
    )

    promotion_id = (
        DWCS_PROMOTION_ID
        if "contender series" in normalized_event_name
        else UFC_PROMOTION_ID
    )

    return {
        "promotion_id": promotion_id,
        "event_name": event["name"],
        "event_date": event.get("event_date"),
        "event_start_time": event.get(
            "event_start_time"
        ),
        "watch_platform": event.get(
            "watch_platform"
        ),
        "venue": event.get("venue"),
        "city": location["city"],
        "state_region": location[
            "state_region"
        ],
        "country": location["country"],
        "event_status": (
            event.get("event_status")
            or "completed"
        ),
        "updated_at": utc_now(),
    }


def compact_event_update(event_data):
    """Do not erase richer schedule metadata with UFCStats nulls."""
    update = {
        key: value
        for key, value in event_data.items()
        if value is not None
    }
    if update.get("event_status") != "completed":
        update.pop("event_status", None)
    return update


# ==========================================
# Event importer
# ==========================================

def import_event(
    event,
    dry_run=True,
):
    """
    Insert a new event or update an existing
    event using its UFCStats external ID.
    """

    event_url = event.get("url")

    if not event_url:
        raise ValueError(
            "Event URL is missing."
        )

    external_id = get_ufcstats_event_id(
        event_url
    )

    existing = event_exists(
        external_id
    )

    event_data = prepare_event(
        event
    )
    existing_event_id = (
        int(existing["internal_id"])
        if existing
        else find_existing_event(event_data)
    )

    # Dry runs must occur before any writes.
    if dry_run:
        action = (
            "UPDATE"
            if existing_event_id is not None
            else "INSERT"
        )

        print(
            "\nDRY RUN — no database changes"
        )
        print("Action:", action)
        print("Event data:", event_data)
        print("UFCStats ID:", external_id)

        return {
            "status": "dry_run",
            "action": action.lower(),
            "event_id": (
                existing_event_id
            ),
        }

    # ======================================
    # Update an existing event
    # ======================================

    if existing:
        event_id = int(
            existing["internal_id"]
        )

        response = (
            supabase
            .table("events")
            .update(compact_event_update(event_data))
            .eq(
                "event_id",
                event_id,
            )
            .execute()
        )

        if not response.data:
            raise RuntimeError(
                "Event update returned no data."
            )

        (
            supabase
            .table("external_ids")
            .update(
                {
                    "external_url": event_url,
                    "updated_at": utc_now(),
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
            event["name"],
        )

        return {
            "status": "updated",
            "event_id": event_id,
        }

    # Attach UFCStats to a schedule/manual row already in the dashboard.
    if existing_event_id is not None:
        response = (
            supabase
            .table("events")
            .update(compact_event_update(event_data))
            .eq("event_id", existing_event_id)
            .execute()
        )
        if not response.data:
            raise RuntimeError(
                "Existing event attachment update returned no data."
            )
        attach_event_mapping(
            existing_event_id,
            external_id,
            event_url,
        )
        print("ATTACHED UFCSTATS:", event["name"])
        return {
            "status": "updated",
            "event_id": existing_event_id,
        }

    # ======================================
    # Insert a new event
    # ======================================

    inserted_event = (
        supabase
        .table("events")
        .insert(event_data)
        .execute()
    )

    if not inserted_event.data:
        raise RuntimeError(
            "Event insert returned no data."
        )

    event_id = int(
        inserted_event.data[0]["event_id"]
    )

    try:
        attach_event_mapping(
            event_id,
            external_id,
            event_url,
        )

    except Exception:
        # Prevent an event from being left behind
        # without its external-ID mapping.
        (
            supabase
            .table("events")
            .delete()
            .eq(
                "event_id",
                event_id,
            )
            .execute()
        )

        raise

    print(
        "\nIMPORTED:",
        event["name"],
    )

    print(
        f"Supabase event ID: {event_id}"
    )

    return {
        "status": "imported",
        "event_id": event_id,
    }


# ==========================================
# Manual test
# ==========================================

if __name__ == "__main__":
    test_event = {
        "name": "UFC Import Test",
        "event_date": "2026-07-29",
        "location": (
            "Las Vegas, NV, United States"
        ),
        "event_status": "completed",
        "url": (
            "http://ufcstats.com/"
            "event-details/test-event-001"
        ),
    }

    result = import_event(
        test_event,
        dry_run=True,
    )

    print("\nResult:")
    print(result)
