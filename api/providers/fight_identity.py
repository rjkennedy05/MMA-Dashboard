"""Keep existing fight identities stable for side-based bets and research."""
from __future__ import annotations

from typing import Any


class FightIdentityError(RuntimeError):
    """An import would reinterpret records already attached to a fight."""


def preserve_fight_identity(
    supabase: Any,
    fight_id: int,
    fight_data: dict[str, Any],
) -> dict[str, Any]:
    """Orient an update to its stored sides; refuse a different event or pair.

    Bet selections, research ratings, and AI picks refer to fighter_a/b. Provider
    ordering is presentation data and must never change those stored identities.
    Winner IDs are fighter identities, so they do not need to be swapped.
    """
    response = (
        supabase.table("fights")
        .select("fight_id,event_id,fighter_a_id,fighter_b_id")
        .eq("fight_id", fight_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise FightIdentityError(
            f"Fight #{fight_id} was not found. Review its provider mapping before importing."
        )
    stored = response.data[0]
    stored_pair = (int(stored["fighter_a_id"]), int(stored["fighter_b_id"]))
    incoming_pair = (int(fight_data["fighter_a_id"]), int(fight_data["fighter_b_id"]))
    if int(stored["event_id"]) != int(fight_data["event_id"]):
        raise FightIdentityError(
            f"Fight #{fight_id} belongs to another event. Existing bets and research "
            "were preserved; review the provider mapping instead of moving this fight."
        )
    if incoming_pair not in (stored_pair, stored_pair[::-1]):
        raise FightIdentityError(
            f"Fight #{fight_id} has different stored participants. Existing bets and "
            "research were preserved; review the replacement or fighter identity mapping."
        )
    return {
        **fight_data,
        "fighter_a_id": stored_pair[0],
        "fighter_b_id": stored_pair[1],
    }
