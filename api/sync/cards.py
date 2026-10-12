"""Shared card import orchestration with all-or-nothing database commits."""

from contextlib import nullcontext

try:
    from providers.atomic import import_batch
    from providers.errors import safe_error
    from sync.transient_retry import run_with_transient_retry
except ModuleNotFoundError:
    from api.providers.atomic import import_batch
    from api.providers.errors import safe_error
    from api.sync.transient_retry import run_with_transient_retry


def import_card(importer, event, fights, *, dry_run=False):
    results = []
    batch = None
    try:
        with nullcontext() if dry_run else import_batch(importer.supabase) as batch:
            saved_event = importer.import_event(event, dry_run=dry_run)
            event_id = saved_event.get("event_id") or 0
            for index, fight in enumerate(fights, 1):
                results.append(
                    importer.import_fight(
                        event_id,
                        fight,
                        fight.get("official_order") or index,
                        dry_run=dry_run,
                    )
                )
            if not dry_run and results:
                ids = {
                    result["fight_id"]
                    for result in results
                    if result.get("fight_id") is not None
                }
                stored = (
                    importer.supabase.table("fights")
                    .select("fight_id,fight_status")
                    .eq("event_id", event_id)
                    .execute()
                    .data
                    or []
                )
                saved_event["unconfirmed_omissions"] = [
                    row["fight_id"]
                    for row in stored
                    if row.get("fight_status") in {"scheduled", "upcoming"}
                    and row["fight_id"] not in ids
                ]
        if batch:
            saved_event["event_id"] = batch.saved_ids.get(
                saved_event["event_id"], saved_event["event_id"]
            )
            saved_event["event_status"] = batch.event_states.get(
                str(saved_event["event_id"])
            )
            if saved_event["event_status"] in {"cancelled", "canceled"}:
                saved_event["unconfirmed_omissions"] = []
            for result in results:
                if result.get("fight_id") is not None:
                    result["fight_id"] = batch.saved_ids.get(
                        result["fight_id"], result["fight_id"]
                    )
        return saved_event, results
    finally:
        # Failed transactions and successful commits must not leave temporary
        # fighter IDs in an importer's name cache for the next card.
        for key in ("_fighter_rows", "_weight_classes"):
            clear = getattr(getattr(importer, key, None), "cache_clear", None)
            if clear:
                clear()


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
            if not args.dry_run:
                if saved["status"] in {"imported", "updated"}:
                    summary["events_" + saved["status"]] += 1
                for result in results:
                    if result["status"] in {"imported", "updated"}:
                        summary["fights_" + result["status"]] += 1
                    elif result["status"] == "skipped_placeholder":
                        counts["placeholder_fights_skipped"] += 1
                if any(
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
                        "event_name": label,
                        "event_date": str(
                            event.get("event_date") or event.get("date") or ""
                        )[:10],
                        "message": "The detail source did not verify the stored card; prior bouts were retained.",
                    }
                )
            if any(result["status"] == "skipped_placeholder" for result in results):
                summary.setdefault("catalog_issues", []).append(
                    {
                        "code": "CARD_SOURCE_PLACEHOLDER",
                        "severity": "warning",
                        "event_name": label,
                        "event_date": str(
                            event.get("event_date") or event.get("date") or ""
                        )[:10],
                        "message": "Some source matchups still have unresolved fighter identities; prior records were retained.",
                    }
                )
            if saved.get("unconfirmed_omissions"):
                issue = {
                    "code": "CARD_SOURCE_OMISSION",
                    "severity": "warning",
                    "event_name": label,
                    "event_date": str(
                        event.get("event_date") or event.get("date") or ""
                    )[:10],
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
                    and not saved.get("unconfirmed_omissions")) or saved.get("event_status") in {"cancelled", "canceled"}:
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
                {"stage": provider_key, "context": label, "message": safe_error(error)}
            )
            print("  CARD IMPORT KEPT PREVIOUS DATA — " + safe_error(error))
    counts["requests"] = getattr(client, "request_count", 0)
    if hasattr(client, "event_source"):
        counts["source"] = client.event_source
        counts["fightcenter_fallbacks"] = client.fightcenter_fallbacks
    run.update(counts)
    run["status"] = "partial" if counts["event_errors"] else "completed"
    for key in promotion_keys:
        summary["providers"][key] = "failed" if counts["event_errors"] else "automatic"
    return verified
