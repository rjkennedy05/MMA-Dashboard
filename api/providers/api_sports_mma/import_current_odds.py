from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from providers.the_odds_api.fight_matcher import load_database_fights, match_api_fight
from providers.the_odds_api.import_one_matchup import import_moneylines
from uploader import supabase

from .client import ApiSportsMmaClient, ApiSportsMmaError
from .normalizer import normalize_odds_fight, partition_dates_for_plan


def _source_id() -> int:
    response = supabase.table("data_sources").select("source_id").eq("name", "API-Sports MMA").limit(1).execute()
    if not response.data:
        raise RuntimeError("API-Sports MMA source is missing. Run migration 202608030011.")
    return int(response.data[0]["source_id"])


def _attach_mapping(source_id: int, fight_id: int, external_id: str) -> None:
    existing = supabase.table("external_ids").select("external_id_map_id").eq("entity_type", "fight").eq("internal_id", fight_id).eq("source_id", source_id).limit(1).execute()
    payload = {"entity_type": "fight", "internal_id": fight_id, "source_id": source_id, "external_id": external_id, "external_url": None}
    if existing.data:
        supabase.table("external_ids").update(payload).eq("external_id_map_id", existing.data[0]["external_id_map_id"]).execute()
    else:
        supabase.table("external_ids").insert(payload).execute()


def _is_plan_date_limit(error: ApiSportsMmaError) -> bool:
    message = str(error).casefold()
    return "free plan" in message or "do not have access to this date" in message


def import_api_sports_odds(
    max_days: int = 4,
    max_requests: int = 10,
    provider_future_days: int = 1,
) -> dict[str, Any]:
    client = ApiSportsMmaClient(max_requests=max_requests)
    database_fights = load_database_fights()
    today = date.today()
    relevant_dates = sorted({
        str((fight.get("events") or {}).get("event_date"))
        for fight in database_fights
        if (fight.get("events") or {}).get("event_date")
        and today <= date.fromisoformat(str(fight["events"]["event_date"])) <= today + timedelta(days=max_days)
        and fight.get("fight_status") not in {"cancelled", "completed", "draw", "no_contest"}
    })
    query_dates, deferred_dates = partition_dates_for_plan(
        relevant_dates, today, provider_future_days
    )
    source_id = _source_id()
    metrics = {
        "status": "completed",
        "key_environment": client.key_environment,
        "expectation_window_days": max_days,
        "provider_future_days": provider_future_days,
        "dates_queried": [],
        "dates_deferred_by_plan": deferred_dates,
        "plan_limited_dates": [],
        "requests": 0,
        "raw_rows": 0,
        "api_matchups": 0,
        "unusable_rows": 0,
        "matched": 0,
        "inserted": 0,
        "unchanged": 0,
        "unmatched": 0,
        "failures": 0,
        "failure_messages": [],
        "remaining": None,
        "sample_top_level_keys": [],
    }
    for event_date in query_dates:
        try:
            raw_rows = client.odds_for_date(event_date)
            metrics["dates_queried"].append(event_date)
        except ApiSportsMmaError as error:
            if _is_plan_date_limit(error):
                metrics["plan_limited_dates"].append(event_date)
                continue
            metrics["failures"] += 1
            metrics["failure_messages"].append(str(error))
            continue
        for raw in raw_rows:
            metrics["raw_rows"] += 1
            if not isinstance(raw, dict):
                metrics["unusable_rows"] += 1
                continue
            if not metrics["sample_top_level_keys"]:
                metrics["sample_top_level_keys"] = sorted(str(key) for key in raw)[:20]
            api_fight = normalize_odds_fight(raw)
            if not api_fight or not api_fight["bookmakers"]:
                metrics["unusable_rows"] += 1
                continue
            metrics["api_matchups"] += 1
            try:
                match = match_api_fight(api_fight, database_fights)
                if match["status"] != "matched":
                    metrics["unmatched"] += 1
                    continue
                fight = match["fight"]
                _attach_mapping(source_id, int(fight["fight_id"]), api_fight["id"])
                result = import_moneylines(api_fight, fight, source_id)
                metrics["matched"] += 1
                metrics["inserted"] += result["inserted"]
                metrics["unchanged"] += result["unchanged"]
            except Exception as error:
                metrics["failures"] += 1
                metrics["failure_messages"].append(str(error))
    metrics["requests"] = client.request_count
    metrics["remaining"] = client.daily_remaining
    if metrics["failures"]:
        metrics["status"] = "partial"
    elif metrics["dates_deferred_by_plan"] or metrics["plan_limited_dates"]:
        metrics["status"] = "completed_limited"
    return metrics
