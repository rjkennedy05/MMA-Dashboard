from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


OFFICIAL_FIGHT_STATUSES = {
    "completed",
    "draw",
    "no_contest",
}


def should_process_ufcstats_event(
    event_date: date | None,
    today: date,
) -> bool:
    """UFCStats is enrichment only; ESPN owns future scheduling."""
    return event_date is not None and event_date <= today


def ufcstats_refresh_reason(
    *,
    fight_external_id: str,
    event_date: date,
    today: date,
    mapped_fights: dict[str, int],
    fight_statuses: dict[int, str],
    refresh_days: int,
    full_repair: bool,
) -> str | None:
    """Return why a fight needs UFCStats work, or None when it is complete."""
    if full_repair:
        return "full_repair"

    fight_id = mapped_fights.get(fight_external_id)
    if fight_id is None:
        return "missing_mapping"

    status = (fight_statuses.get(fight_id) or "").casefold()
    if status not in OFFICIAL_FIGHT_STATUSES:
        return "missing_result"

    cutoff = today - timedelta(days=max(0, refresh_days))
    if event_date >= cutoff:
        return "recent_result_check"

    return None


@dataclass
class UfcstatsSyncState:
    mapped_fights: dict[str, int]
    fight_statuses: dict[int, str]

    @classmethod
    def load(cls, supabase_client: Any, source_id: int) -> "UfcstatsSyncState":
        mappings_response = (
            supabase_client.table("external_ids")
            .select("external_id, internal_id")
            .eq("entity_type", "fight")
            .eq("source_id", source_id)
            .execute()
        )
        mapped_fights = {
            str(row["external_id"]): int(row["internal_id"])
            for row in mappings_response.data or []
        }

        fights_response = (
            supabase_client.table("fights")
            .select("fight_id, fight_status")
            .execute()
        )
        mapped_ids = set(mapped_fights.values())
        fight_statuses = {
            int(row["fight_id"]): str(row.get("fight_status") or "")
            for row in fights_response.data or []
            if int(row["fight_id"]) in mapped_ids
        }
        return cls(mapped_fights, fight_statuses)

    def refresh_reason(
        self,
        *,
        fight_external_id: str,
        event_date: date,
        today: date,
        refresh_days: int,
        full_repair: bool,
    ) -> str | None:
        return ufcstats_refresh_reason(
            fight_external_id=fight_external_id,
            event_date=event_date,
            today=today,
            mapped_fights=self.mapped_fights,
            fight_statuses=self.fight_statuses,
            refresh_days=refresh_days,
            full_repair=full_repair,
        )

    def mark_processed(
        self,
        fight_external_id: str,
        fight_id: int,
        fight_status: str | None,
    ) -> None:
        self.mapped_fights[fight_external_id] = fight_id
        self.fight_statuses[fight_id] = fight_status or ""
