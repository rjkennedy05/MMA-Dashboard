"""Shared card imports with isolated bout reviews and coordinated commits."""

from contextlib import nullcontext
from datetime import datetime
from zoneinfo import ZoneInfo
import re

try:
    from providers.atomic import import_batch
    from providers.errors import safe_error
    from sync.transient_retry import run_with_transient_retry, is_transient_connection_error
except ModuleNotFoundError:
    from api.providers.atomic import import_batch
    from api.providers.errors import safe_error
    from api.sync.transient_retry import run_with_transient_retry, is_transient_connection_error


def clear_import_caches(importer):
    for key in ("_fighter_rows", "_weight_classes"):
        clear = getattr(getattr(importer, key, None), "cache_clear", None)
        if clear:
            clear()


def recoverable_bout_error(error):
    code = str(getattr(error, "code", ""))
    text = str(error).casefold()
    return not (is_transient_connection_error(error) or code.startswith("PGRST3")
                or code in {"55P03", "PGRST202", "42501", "42P01", "42883"}
                or any(marker in text for marker in ("lease was lost", "lease expired", "another dashboard import",
                                                     "parent import lease", "migration 032", "migration 036")))


def review_result(error, group, original=None):
    message = safe_error(error)
    match = re.search(r"Fight\s*#(\d+)", message, re.I)
    original = original or {}
    fid = original.get("fight_id")
    return {"status": "review", "fight_id": int(match[1]) if match else fid if fid and int(fid)>0 else None,
            "fight_status": None, "message": message, "_group": str(group)}


def card_day(event):
    value = event.get("event_date") or event.get("date") or ""
    try:
        instant = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if instant.tzinfo:
            return instant.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    except ValueError:
        pass
    return str(value)[:10]


def import_card(importer, event, fights, *, dry_run=False):
    results = []
    batch = None
    try:
        with nullcontext() if dry_run else import_batch(importer.supabase) as batch:
            saved_event = importer.import_event(event, dry_run=dry_run)
            event_id = saved_event.get("event_id") or 0
            for index, fight in enumerate(fights, 1):
                try:
                    with batch.bout(index) if batch else nullcontext():
                        result = importer.import_fight(event_id, fight, fight.get("official_order") or index,
                                                       dry_run=dry_run)
                        results.append({**result, "_group": str(index)})
                except Exception as error:
                    if not recoverable_bout_error(error):
                        raise
                    results.append(review_result(error, index))
                    clear_import_caches(importer)
        if batch:
            saved_event["event_id"] = batch.saved_ids.get(
                saved_event["event_id"], saved_event["event_id"]
            )
            saved_event["event_status"] = batch.event_states.get(
                str(saved_event["event_id"])
            )
            if saved_event["event_status"] in {"cancelled", "canceled"}:
                saved_event["unconfirmed_omissions"] = []
            failed = {str(item["group"]): item for item in batch.failed_groups}
            results = [review_result(failed[row["_group"]]["message"], row["_group"], row)
                       if row["_group"] in failed else row for row in results]
            for result in results:
                if result.get("fight_id") is not None:
                    result["fight_id"] = batch.saved_ids.get(
                        result["fight_id"], result["fight_id"]
                    )
        saved_event["fight_reviews"] = [row for row in results if row["status"] == "review"]
        if not dry_run and results:
            ids = {row["fight_id"] for row in results if row.get("fight_id")}
            stored = importer.supabase.table("fights").select("fight_id,fight_status").eq(
                "event_id", saved_event["event_id"]).execute().data or []
            saved_event["unconfirmed_omissions"] = [row["fight_id"] for row in stored
                if row.get("fight_status") in {"scheduled", "upcoming"} and row["fight_id"] not in ids]
            if saved_event.get("event_status") in {"cancelled", "canceled"}:
                saved_event["unconfirmed_omissions"] = []
        return saved_event, results
    finally:
        # Failed transactions and successful commits must not leave temporary
        # fighter IDs in an importer's name cache for the next card.
        clear_import_caches(importer)


def process_cards(
    args,
    summary,
    client,
    importer,
    all_events,
    events,
    provider_key,
    promotion_keys,
    name,
    fetch,
    should_refresh,
    mark_refreshed,
):
    if not all_events:
        raise RuntimeError(
            f"{provider_key} returned no recognizable events; its coverage could not be verified."
        )
    run = summary["provider_runs"][provider_key]
    discovery_unavailable = all(row.get("_followup_event_id") for row in all_events)
    if discovery_unavailable:
        summary["warnings"].append({"stage": provider_key,
            "message": "Only previously saved event identities were available; new event discovery could not be verified."})
    counts = {
        "events": len(events),
        "fights": 0,
        "results": 0,
        "requests": 0,
        "event_errors": 0,
        "fight_errors": 0,
        "events_skipped_fresh": 0,
        "card_changes_archived": 0,
        "placeholder_fights_skipped": 0,
        "cardless_events_skipped": 0,
        "events_awaiting_card": 0,
    }
    summary["events_seen"] += len(all_events)
    summary["events_in_window"] += len(events)
    run["status"] = "running"
    verified = []
    for index, listed in enumerate(events, 1):
        results, reviews = [], []
        followup_failed = True
        label = name(listed)
        print(f"[{provider_key} {index}/{len(events)}] {label}")
        if not should_refresh(args, provider_key, listed):
            counts["events_skipped_fresh"] += 1
            continue
        try:
            event, fights, warnings = fetch(listed)
            summary["fights_seen"] += len(fights)
            counts["fights"] += len(fights)
            saved, results = run_with_transient_retry(
                lambda: import_card(importer, event, fights, dry_run=args.dry_run),
                label=label,
                attempts=3,
            )
            reviews = saved.get("fight_reviews") or []
            followup_failed = bool(reviews)
            if reviews:
                counts["fight_errors"] += len(reviews)
                review_ids = [row["fight_id"] for row in reviews if row.get("fight_id")]
                summary["errors"].append({"stage": provider_key, "context": label,
                    "event_id": saved.get("event_id"), "event_date": card_day(event), "fight_ids": review_ids,
                    "message": "; ".join(row["message"] for row in reviews)})
            if not args.dry_run:
                summary.setdefault("checked_event_ids", []).append(saved["event_id"])
                if saved["status"] in {"imported", "updated"}:
                    summary["events_" + saved["status"]] += 1
                for result in results:
                    if result["status"] in {"imported", "updated"}:
                        summary["fights_" + result["status"]] += 1
                    elif result["status"] == "skipped_placeholder":
                        counts["placeholder_fights_skipped"] += 1
                if not reviews and any(
                    result["status"] in {"imported", "updated"} for result in results
                ):
                    mark_refreshed(args, provider_key, listed)
            if not any(
                result["status"] in {"imported", "updated", "dry_run"}
                for result in results
            ) and saved.get("event_status") not in {"cancelled", "canceled"}:
                counts["events_awaiting_card"] += 1
                summary.setdefault("catalog_issues", []).append(
                    {
                        "code": "CARD_SOURCE_EMPTY",
                        "event_id": saved["event_id"],
                        "event_name": label,
                        "event_date": card_day(event),
                        "message": "The detail source did not verify the stored card; prior bouts were retained.",
                    }
                )
            if any(result["status"] == "skipped_placeholder" for result in results):
                summary.setdefault("catalog_issues", []).append(
                    {
                        "code": "CARD_SOURCE_PLACEHOLDER",
                        "event_id": saved["event_id"],
                        "severity": "warning",
                        "event_name": label,
                        "event_date": card_day(event),
                        "message": "Some source matchups still have unresolved fighter identities; prior records were retained.",
                    }
                )
            if saved.get("unconfirmed_omissions"):
                issue = {
                    "code": "CARD_SOURCE_OMISSION",
                    "event_id": saved["event_id"],
                    "severity": "warning",
                    "event_name": label,
                    "event_date": card_day(event),
                    "fight_ids": saved["unconfirmed_omissions"],
                    "message": "Scheduled matchups were omitted by the source. Prior rows and bets were retained for review.",
                }
                summary.setdefault("catalog_issues", []).append(issue)
                summary["warnings"].append(
                    {
                        "stage": provider_key,
                        "context": label,
                        "message": issue["message"],
                    }
                )
            if (results and all(result["status"] in {"imported", "updated", "dry_run"}
                                for result in results)
                    and not saved.get("unconfirmed_omissions") and not reviews) or saved.get("event_status") in {"cancelled", "canceled"}:
                verified.append(listed)
            for result in results:
                if result.get("fight_status") in {"completed", "draw", "no_contest"}:
                    summary["official_results_found"] += 1
                    counts["results"] += 1
            for warning in warnings:
                summary["warnings"].append(
                    {"stage": provider_key, "context": label, "message": warning}
                )
        except Exception as error:
            counts["event_errors"] += 1
            summary["errors"].append(
                {"stage": provider_key, "context": label, "event_date": card_day(listed),
                 "message": safe_error(error)}
            )
            print("  CARD IMPORT KEPT PREVIOUS DATA — " + safe_error(error))
        finally:
            eid = listed.get("_followup_event_id")
            cache = getattr(args, "followup_cache", None)
            if eid and cache:
                try:
                    cache.mark(eid, failed=followup_failed,
                               source_complete=bool(results) and all(row.get("fight_status") in
                                   {"completed", "draw", "no_contest", "cancelled"} for row in results))
                except OSError as error:
                    summary["warnings"].append({"stage": "result_followup", "context": label,
                        "message": "Result retry state could not be saved: " + safe_error(error)})
    counts["requests"] = getattr(client, "request_count", 0)
    if hasattr(client, "event_source"):
        counts["source"] = client.event_source
        counts["fightcenter_fallbacks"] = client.fightcenter_fallbacks
    run.update(counts)
    run["status"] = "partial" if counts["event_errors"] or counts["fight_errors"] or discovery_unavailable else "completed"
    for key in promotion_keys:
        summary["providers"][key] = "failed" if counts["event_errors"] else "automatic"
    return verified
