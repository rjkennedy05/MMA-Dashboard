"""Reconcile manual observations with a newer database card without losing gaps."""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import re
import unicodedata

TERMINAL = {"completed", "draw", "no_contest", "cancelled"}
RESULT_FIELDS = (
    "fight_status",
    "winner_id",
    "result_type",
    "method",
    "finish_round",
    "finish_time_seconds",
    "result_confirmed_at",
)


def timestamp(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else None
    except (ValueError, TypeError):
        return None


def pair(row):
    def name(side):
        value = (row.get(side) or {}).get("full_name", "")
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode()
            .casefold()
        )
        return re.sub("[^a-z0-9]", "", value)

    names = tuple(sorted((name("fighter_a"), name("fighter_b"))))
    return (names, str(row.get("ruleset") or "MMA").casefold()) if all(names) else None


def merge_external(data, state, now=None):
    merged = deepcopy(data)
    now = now or datetime.now(timezone.utc)
    for event in merged["events"]:
        eid = str(event["event_id"])
        item = state.get("events", {}).get(eid, {})
        card = item.get("external_card") or {}
        observed = timestamp(card.get("checked_at"))
        stored = timestamp(event.get("card_observed_at") or event.get("updated_at"))
        fights = [f for f in merged["fights"] if str(f["event_id"]) == eid]
        id_map = {}
        fighter_map = {}
        if observed and observed <= now + timedelta(minutes=5):
            for direct in card.get("fights", []):
                candidates = [
                    f for f in fights if str(f["fight_id"]) == str(direct["fight_id"])
                ]
                if not candidates and pair(direct):
                    candidates = [f for f in fights if pair(f) == pair(direct)]
                if len(candidates) > 1:
                    continue
                target = candidates[0] if candidates else None
                if target:
                    id_map[str(direct["fight_id"])] = target["fight_id"]
                    for side in ("fighter_a", "fighter_b"):
                        for other in ("fighter_a", "fighter_b"):
                            if pair(
                                {
                                    "fighter_a": direct.get(side),
                                    "fighter_b": direct.get(side),
                                }
                            ) is not None and pair(
                                {
                                    "fighter_a": direct.get(side),
                                    "fighter_b": direct.get(side),
                                }
                            ) == pair(
                                {
                                    "fighter_a": target.get(other),
                                    "fighter_b": target.get(other),
                                }
                            ):
                                fighter_map[str(direct.get(side + "_id"))] = target.get(
                                    other + "_id"
                                )
                seen = timestamp((target or {}).get("source_observed_at")) or stored
                fresh = (not seen or observed > seen) and now - observed <= timedelta(
                    hours=72
                )
                if not fresh:
                    continue
                value = deepcopy(direct)
                if target:
                    value["fight_id"] = target["fight_id"]
                    value["event_id"] = target["event_id"]
                    # Stored A/B is the stable betting identity; remap a reversed direct card.
                    for side in ("fighter_a", "fighter_b"):
                        value[side] = deepcopy(target.get(side))
                        value[side + "_id"] = target.get(side + "_id")
                    value["winner_id"] = fighter_map.get(
                        str(direct.get("winner_id")), direct.get("winner_id")
                    )
                    confirmation = timestamp(target.get("result_confirmed_at"))
                    if target.get("fight_status") in TERMINAL and (
                        direct.get("fight_status") not in TERMINAL
                        or (confirmation and confirmation >= observed)
                    ):
                        for field in RESULT_FIELDS:
                            value[field] = target.get(field)
                    target.update(value)
                else:
                    fights.append(value)
            if (not stored or observed > stored) and now - observed <= timedelta(
                hours=72
            ):
                update = deepcopy(card.get("event") or {})
                update.pop("event_id", None)
                if (
                    event.get("event_status") in TERMINAL
                    and update.get("event_status") not in TERMINAL
                ):
                    update.pop("event_status", None)
                event.update(update)
            if card.get("source_url") and merged.get("links") is not None:
                merged["links"].append(
                    {
                        "internal_id": event["event_id"],
                        "external_url": card["source_url"],
                    }
                )
        merged["fights"] = [
            f for f in merged["fights"] if str(f["event_id"]) != eid
        ] + fights
        if merged.get("odds") is None:
            continue
        existing = {}
        for row in merged["odds"]:
            key = (
                str(row["fight_id"]),
                str(row["fighter_id"]),
                str(row.get("sportsbook_key") or row.get("sportsbook")),
            )
            before = timestamp(
                (existing.get(key) or {}).get("provider_updated_at")
                or (existing.get(key) or {}).get("recorded_at")
            )
            after = timestamp(row.get("provider_updated_at") or row.get("recorded_at"))
            if not before or (after and after >= before):
                existing[key] = row
        for direct in item.get("direct_odds", []):
            row = deepcopy(direct)
            row["fight_id"] = id_map.get(str(row["fight_id"]), row["fight_id"])
            row["fighter_id"] = fighter_map.get(
                str(row["fighter_id"]), row["fighter_id"]
            )
            observed = timestamp(row.get("observed_at") or row.get("recorded_at"))
            if (
                not observed
                or now - observed > timedelta(hours=24)
                or observed > now + timedelta(minutes=5)
            ):
                continue
            key = (
                str(row["fight_id"]),
                str(row["fighter_id"]),
                str(row.get("sportsbook_key") or row.get("sportsbook")),
            )
            before = timestamp(
                (existing.get(key) or {}).get("provider_updated_at")
                or (existing.get(key) or {}).get("recorded_at")
            )
            after = timestamp(row.get("provider_updated_at")) or observed
            if before and after < before:
                continue
            merged["odds"].append(row)  # Keep opening/close snapshots and absent books.
    return merged
