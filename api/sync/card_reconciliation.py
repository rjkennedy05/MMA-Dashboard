from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def missing_scheduled_fight_ids(
    existing_fights: Iterable[dict[str, Any]],
    active_fight_ids: Iterable[int],
) -> list[int]:
    active = {int(fight_id) for fight_id in active_fight_ids if fight_id is not None}
    if not active:
        return []

    return sorted(
        int(fight["fight_id"])
        for fight in existing_fights
        if fight.get("fight_id") is not None
        and fight.get("fight_status") in {"scheduled", "upcoming"}
        and int(fight["fight_id"]) not in active
    )


def archive_missing_scheduled_fights(
    supabase: Any,
    event_id: int,
    active_fight_ids: Iterable[int],
    *,
    confirmed_cancelled_ids: Iterable[int] = (),
) -> list[int]:
    """Only explicit cancellation evidence can cancel an omitted matchup.

    A successful nonempty response is not evidence of a complete source card.
    Existing callers preserve omitted fights; normalized explicit cancellations
    continue to be saved through their ordinary fight imports.
    """
    active = [int(fight_id) for fight_id in active_fight_ids if fight_id is not None]
    confirmed = {int(value) for value in confirmed_cancelled_ids}
    if not active or not confirmed:
        return []

    response = (
        supabase.table("fights")
        .select("fight_id,fight_status")
        .eq("event_id", event_id)
        .in_("fight_status", ["scheduled", "upcoming"])
        .execute()
    )
    stale_ids = [value for value in missing_scheduled_fight_ids(response.data or [], active) if value in confirmed]
    if not stale_ids:
        return []

    (
        supabase.table("fights")
        .update({
            "fight_status": "cancelled",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        .in_("fight_id", stale_ids)
        .execute()
    )
    return stale_ids
