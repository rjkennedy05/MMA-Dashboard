import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv,dotenv_values
from supabase import create_client

from matching import matching_event_id

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
from providers.atomic import AtomicImportClient
from providers.database import table_rows
from providers.manifest import promotion_key
from providers.persistence import find_identity, save_entity
from providers.configuration import validate_project_urls


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
SUPABASE_SERVICE_KEY = (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
                        or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


class LazyImportClient(AtomicImportClient):
    def __init__(self):self._raw=None

    @property
    def raw(self):
        if self._raw is None:
            url=os.getenv("SUPABASE_URL")
            key=(os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
            if not url:raise ValueError("SUPABASE_URL is missing from api/.env")
            if not key:raise ValueError("A server-side Supabase key is missing from api/.env")
            frontend=os.getenv("VITE_SUPABASE_URL") or dotenv_values(API_ROOT.parent/".env").get("VITE_SUPABASE_URL")
            validate_project_urls(url,frontend)
            self._raw=create_client(url,key)
        return self._raw

supabase = LazyImportClient()


@lru_cache(maxsize=1)
def get_ufcstats_source_id():
    rows = table_rows(supabase, "data_sources", "source_id,name", "source_id")
    matches = [row for row in rows if row["name"].casefold().replace(" ", "") == "ufcstats"]
    if len(matches) != 1:
        raise RuntimeError("UFCStats source cannot be resolved uniquely; review data_sources.")
    return int(matches[0]["source_id"])


@lru_cache(maxsize=2)
def get_promotion_id(key):
    rows = table_rows(supabase, "promotions", "promotion_id,name", "promotion_id")
    matches = [row for row in rows if promotion_key(row["name"]) == key]
    if len(matches) != 1:
        raise RuntimeError(f"{key.upper()} promotion cannot be resolved uniquely.")
    return int(matches[0]["promotion_id"])


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
    return find_identity(supabase, "event", get_ufcstats_source_id(), external_id)


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
    save_entity(supabase,"event",{},get_ufcstats_source_id(),external_id,event_id,event_url)


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
        get_promotion_id("dwcs")
        if "contender series" in normalized_event_name
        else get_promotion_id("ufc")
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

    event_data.pop("event_status",None)
    if existing_event_id is None:event_data["event_status"]="unknown"
    result = save_entity(supabase, "event", compact_event_update(event_data),
                         get_ufcstats_source_id(), external_id, existing_event_id, event_url)
    return {"status": result["status"], "event_id": int(result["internal_id"])}


# ==========================================
# Manual test
# ==========================================

if __name__ == "__main__":
    raise SystemExit("Use api/sync/weekly_sync.py --mode repair to run a coordinated import. Helper modules do not run test writes against your database.")
