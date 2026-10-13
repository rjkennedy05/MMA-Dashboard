from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def configure_utf8_console() -> None:
    """Keep provider progress output Unicode-safe on Windows consoles/pipes."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


configure_utf8_console()


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "api"
UFCSTATS_ROOT = API_ROOT / "ufcstats"
ODDS_IMPORTER = (
    API_ROOT
    / "providers"
    / "the_odds_api"
    / "import_current_odds.py"
)
REPORTS_ROOT = Path(__file__).resolve().parent / "reports"
FRESHNESS_STATE = Path(__file__).resolve().parent / "state" / "event_freshness.json"

sys.path.insert(0, str(UFCSTATS_ROOT))
sys.path.insert(0, str(API_ROOT))

from fight_importer import import_fight  # noqa: E402
from fight_detail_scraper import parse_fight_detail  # noqa: E402
from fight_round_stats_importer import (  # noqa: E402
    import_fight_round_stats,
)
from fight_stats_scraper import (  # noqa: E402
    UfcstatsStatsUnavailableError,
    parse_fight_stats,
)
from fight_scraper import get_fights_from_event  # noqa: E402
from page_reader import UfcstatsPageReader  # noqa: E402
from scraper import get_events  # noqa: E402
from uploader import import_event, supabase  # noqa: E402
from providers.espn_mma.client import (  # noqa: E402
    EspnMmaClient,
    EspnMmaNoFightCardError,
)
from providers.espn_mma.importer import (  # noqa: E402
    PflImporter,
    UfcImporter,
)
from providers.espn_mma.normalizer import (  # noqa: E402
    event_fights,
    event_in_window,
    event_name,
    matchup_label as espn_matchup_label,
    normalized_status,
)
from providers.one_championship.client import (  # noqa: E402
    OneChampionshipClient,
)
from providers.one_championship.importer import (  # noqa: E402
    OneChampionshipImporter,
)
from providers.one_championship.normalizer import (  # noqa: E402
    dashboard_event_date as one_dashboard_event_date,
    enrich_event as enrich_one_event,
    event_in_window as one_event_in_window,
    event_name as one_event_name,
    event_status_url as one_event_status_url,
    normalized_status as one_normalized_status,
    parse_event_listing as parse_one_event_listing,
    parse_fights as parse_one_fights,
)
from providers.lfa.client import LfaClient  # noqa: E402
from providers.lfa.importer import LfaImporter  # noqa: E402
from providers.lfa.normalizer import (  # noqa: E402
    event_in_window as lfa_event_in_window,
    event_name as lfa_event_name,
    merge_event_listings as merge_lfa_event_listings,
    normalized_status as lfa_normalized_status,
    parse_official_events as parse_lfa_official_events,
    parse_sherdog_fights as parse_lfa_fights,
    parse_sherdog_index as parse_lfa_sherdog_index,
    sherdog_event_url as lfa_sherdog_event_url,
)
from providers.bkfc.client import BkfcClient, BkfcProviderError  # noqa: E402
from providers.bkfc.importer import BkfcImporter  # noqa: E402
from providers.bkfc.normalizer import (  # noqa: E402
    enrich_event as enrich_bkfc_event,
    event_in_window as bkfc_event_in_window,
    event_name as bkfc_event_name,
    event_stats_url as bkfc_event_stats_url,
    merge_event_listings as merge_bkfc_event_listings,
    normalized_status as bkfc_normalized_status,
    parse_event_listing as parse_bkfc_event_listing,
    parse_fights as parse_bkfc_fights,
)
from providers.api_sports_mma.client import (  # noqa: E402
    API_SPORTS_KEY_NAMES,
    ENV_PATHS as API_SPORTS_ENV_PATHS,
    resolve_api_sports_key,
)
from providers.event_catalog.sync import sync_official_catalogs  # noqa: E402
from providers.manifest import active_promotions  # noqa: E402
from sync.data_quality import audit_upcoming_coverage  # noqa: E402
from sync.freshness import EventFreshnessCache  # noqa: E402
from sync.incremental import (  # noqa: E402
    UfcstatsSyncState,
    should_process_ufcstats_event,
)
from sync.transient_retry import run_with_transient_retry  # noqa: E402
from sync.card_reconciliation import (  # noqa: E402
    archive_missing_scheduled_fights,
)


OFFICIAL_RESULT_STATUSES = {
    "completed",
    "draw",
    "no_contest",
}

PROVIDER_COVERAGE = {
    "ufc": "automatic",
    "dwcs": "automatic",
    "pfl": "adapter_ready",
    "one": "adapter_ready",
    "bkfc": "adapter_ready",
    "lfa": "adapter_ready",
}

if set(PROVIDER_COVERAGE) != set(active_promotions()):
    raise RuntimeError("Provider coverage and active-promotion manifest disagree.")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_progress(stage: str, status: str, label: str) -> None:
    print(
        "SYNC_STAGE="
        + json.dumps(
            {"stage": stage, "status": status, "label": label, "at": utc_now()},
            ensure_ascii=False,
        ),
        flush=True,
    )


def timed_stage(
    summary: dict[str, Any],
    stage: str,
    label: str,
    operation,
):
    started = time.monotonic()
    emit_progress(stage, "running", label)
    try:
        result = operation()
    except Exception:
        seconds = round(time.monotonic() - started, 2)
        summary["stage_timings"][stage] = seconds
        emit_progress(stage, "failed", f"{label} needs review · {seconds:.1f}s")
        raise
    seconds = round(time.monotonic() - started, 2)
    summary["stage_timings"][stage] = seconds
    emit_progress(stage, "completed", f"{label} · {seconds:.1f}s")
    return result


def event_external_key(event: dict[str, Any]) -> str:
    return str(
        event.get("external_id")
        or event.get("id")
        or event.get("external_url")
        or event.get("event_url")
        or event.get("name")
        or event.get("event_name")
        or "unknown"
    )


def should_refresh_listing(
    args: argparse.Namespace,
    provider: str,
    event: dict[str, Any],
) -> bool:
    cache = getattr(args, "freshness_cache", None)
    if cache is None or args.mode != "daily":
        return True
    return cache.should_refresh(
        provider,
        event_external_key(event),
        parse_event_date(event),
        event,
        force=args.requested_scope != "all",
    )


def mark_listing_refreshed(
    args: argparse.Namespace,
    provider: str,
    event: dict[str, Any],
) -> None:
    cache = getattr(args, "freshness_cache", None)
    if cache is not None:
        cache.mark(provider, event_external_key(event), event)


def parse_event_date(event: dict[str, Any]) -> date | None:
    value = event.get("event_date") or event.get("date")

    if not value:
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def archive_upcoming_card_changes(
    event: dict[str, Any],
    today: date,
    event_id: int,
    active_fight_ids: list[int],
) -> list[int]:
    event_date = parse_event_date(event)
    if event_date is None or event_date < today:
        return []
    return archive_missing_scheduled_fights(
        supabase, event_id, active_fight_ids
    )


def event_is_in_window(
    event: dict[str, Any],
    today: date,
    past_days: int,
    future_days: int,
) -> bool:
    event_date = parse_event_date(event)

    if event_date is None:
        return False

    return (
        today - timedelta(days=past_days)
        <= event_date
        <= today + timedelta(days=future_days)
    )


def empty_summary(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "started_at": utc_now(),
        "finished_at": None,
        "status": "running",
        "dry_run": args.dry_run,
        "run_mode": args.mode,
        "requested_scope": args.requested_scope,
        "window": {
            "past_days": args.past_days,
            "future_days": args.future_days,
        },
        "providers": dict(PROVIDER_COVERAGE),
        "provider_runs": {
            "official_catalog": {"status": "not_run", "catalogs": {}},
            "espn_ufc": {"status": "not_run"},
            "ufcstats": {"status": "not_run"},
            "espn_mma": {"status": "not_run"},
            "one_championship": {"status": "not_run"},
            "lfa": {"status": "not_run"},
            "bkfc": {"status": "not_run"},
            "the_odds_api": {"status": "not_run"},
            "api_sports_mma": {"status": "not_run"},
            "fightodds": {"status": "not_run"},
        },
        "events_seen": 0,
        "events_in_window": 0,
        "events_imported": 0,
        "events_updated": 0,
        "fights_seen": 0,
        "fights_imported": 0,
        "fights_updated": 0,
        "official_results_found": 0,
        "stat_rows_processed": 0,
        "odds_status": "not_run",
        "retention": {"status": "disabled_history_preserved"},
        "history_check": {"status": "not_run"},
        "quality_audit": {"status": "not_run", "issues": []},
        "catalog_issues": [],
        "stage_timings": {},
        "warnings": [],
        "errors": [],
    }


def add_error(
    summary: dict[str, Any],
    stage: str,
    message: str,
    context: str | None = None,
) -> None:
    summary["errors"].append(
        {
            "stage": stage,
            "message": message,
            "context": context,
        }
    )


def sync_ufcstats(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    provider_run = summary["provider_runs"]["ufcstats"]
    provider_run["status"] = "running"
    today = date.today()
    events = get_events(headless=not args.show_browser)
    summary["events_seen"] += len(events)

    if not events:
        raise RuntimeError(
            "UFCStats returned no events; the page or scraper needs review."
        )

    selected_events = [
        event
        for event in events
        if event_is_in_window(
            event,
            today=today,
            past_days=args.past_days,
            future_days=args.future_days,
        )
    ]
    selected_events.sort(
        key=lambda event: event.get("event_date") or ""
    )
    summary["events_in_window"] += len(selected_events)
    processable_events = [
        event
        for event in selected_events
        if should_process_ufcstats_event(parse_event_date(event), today)
    ]
    future_events_skipped = len(selected_events) - len(processable_events)
    provider_counts = {
        "events": len(processable_events),
        "future_events_skipped": future_events_skipped,
        "fights_refreshed": 0,
        "fights_skipped_complete": 0,
        "stats_unavailable": 0,
        "full_repair": bool(args.full_repair),
        "refresh_days": args.stats_refresh_days,
    }

    print(
        "\nUFCStats events in sync window: "
        f"{len(selected_events)} of {len(events)}; "
        f"{future_events_skipped} future schedule event(s) skipped\n"
    )

    state = None if args.dry_run else UfcstatsSyncState.load(supabase)

    with ExitStack() as stack:
        page_reader: UfcstatsPageReader | None = None

        for event_index, event in enumerate(processable_events, start=1):
            event_label = event.get("name") or "Unknown event"
            event_date = parse_event_date(event)
            if event_date is None:
                continue
            print(
                f"[{event_index}/{len(processable_events)}] "
                f"{event_label}"
            )

            try:
                event_result = import_event(
                    event,
                    dry_run=args.dry_run,
                )

                if event_result["status"] == "imported":
                    summary["events_imported"] += 1
                elif event_result["status"] == "updated":
                    summary["events_updated"] += 1
            except Exception as error:
                add_error(
                    summary,
                    stage="event_import",
                    message=str(error),
                    context=event_label,
                )
                print(f"  EVENT FAILED — {error}")
                continue

            try:
                fights = get_fights_from_event(event["url"])
                summary["fights_seen"] += len(fights)
            except Exception as error:
                add_error(
                    summary,
                    stage="fight_list",
                    message=str(error),
                    context=event_label,
                )
                print(f"  FIGHT LIST FAILED — {error}")
                continue

            if args.dry_run:
                target = event_result.get("event_id") or "new row"
                print(
                    "  DRY RUN — "
                    f"{event_result.get('action', 'review')} {target}; "
                    f"found {len(fights)} fights"
                )
                continue

            for fight in fights:
                matchup = (
                    f"{fight.get('fighter_a_name')} vs "
                    f"{fight.get('fighter_b_name')}"
                )
                fight_url = fight.get("fight_url")
                if not fight_url:
                    add_error(
                        summary,
                        stage="fight_import",
                        message="Fight URL is missing.",
                        context=f"{event_label}: {matchup}",
                    )
                    continue
                fight_external_id = fight_url.rstrip("/").split("/")[-1]
                refresh_reason = state.refresh_reason(
                    fight_external_id=fight_external_id,
                    event_date=event_date,
                    today=today,
                    refresh_days=args.stats_refresh_days,
                    full_repair=args.full_repair,
                )
                if refresh_reason is None:
                    provider_counts["fights_skipped_complete"] += 1
                    continue

                if page_reader is None:
                    page_reader = stack.enter_context(
                        UfcstatsPageReader(headless=not args.show_browser)
                    )

                try:
                    html = page_reader.read(fight_url)
                    detail = parse_fight_detail(html, fight_url)
                    fight_result = import_fight(
                        event["url"],
                        fight,
                        dry_run=False,
                        detail=detail,
                    )
                    provider_counts["fights_refreshed"] += 1

                    if fight_result["status"] == "imported":
                        summary["fights_imported"] += 1
                    elif fight_result["status"] == "updated":
                        summary["fights_updated"] += 1

                    fight_status = fight_result.get("fight_status")
                    fight_id = int(fight_result["fight_id"])
                    state.mark_processed(
                        fight_external_id,
                        fight_id,
                        fight_status,
                    )

                    if fight_status in OFFICIAL_RESULT_STATUSES:
                        summary["official_results_found"] += 1
                except Exception as error:
                    add_error(
                        summary,
                        stage="fight_import",
                        message=str(error),
                        context=f"{event_label}: {matchup}",
                    )
                    print(f"  FIGHT FAILED — {matchup}: {error}")
                    continue

                if args.skip_stats or fight_status not in OFFICIAL_RESULT_STATUSES:
                    continue

                try:
                    normalized_stats = parse_fight_stats(html)
                    stats_result = import_fight_round_stats(
                        fight_url,
                        dry_run=False,
                        normalized_stats=normalized_stats,
                    )
                    summary["stat_rows_processed"] += int(
                        stats_result.get("round_rows") or 0
                    )
                except UfcstatsStatsUnavailableError as error:
                    provider_counts["stats_unavailable"] += 1
                    print(f"  STATS PENDING — {matchup}: {error}")
                except Exception as error:
                    add_error(
                        summary,
                        stage="stats_import",
                        message=str(error),
                        context=f"{event_label}: {matchup}",
                    )
                    print(f"  STATS FAILED — {matchup}: {error}")

    provider_run.update(provider_counts)
    provider_run["status"] = "completed"


def sync_ufc(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    provider_run = summary["provider_runs"]["espn_ufc"]

    if args.skip_ufc:
        provider_run["status"] = "skipped"
        return

    client = EspnMmaClient(league="ufc")
    provider_run["status"] = "running"
    today = date.today()
    window_start = today - timedelta(days=args.past_days)
    window_end = today + timedelta(days=args.future_days)
    all_events = client.get_events_in_window(window_start, window_end)
    events = [
        event
        for event in all_events
        if event_in_window(event, window_start, window_end)
    ]
    events.sort(key=lambda event: (event.get("date") or "", event_name(event)))
    importer = UfcImporter(supabase)

    summary["events_seen"] += len(all_events)
    summary["events_in_window"] += len(events)
    provider_counts = {
        "events": len(events),
        "fights": 0,
        "results": 0,
        "requests": 0,
        "event_errors": 0,
        "card_changes_archived": 0,
        "fight_errors": 0,
        "placeholder_fights_skipped": 0,
        "cardless_events_skipped": 0,
        "events_skipped_fresh": 0,
        "transient_retries": 0,
    }

    def retry_database_operation(operation, label):
        def prepare_retry(_attempt, _error):
            provider_counts["transient_retries"] += 1
            importer.clear_lookup_caches()

        return run_with_transient_retry(
            operation,
            label=label,
            on_retry=prepare_retry,
        )

    print(
        "\nESPN UFC/DWCS events in sync window: "
        f"{len(events)} of {len(all_events)} "
        f"(source: {client.event_source})\n"
    )

    for event_index, event in enumerate(events, start=1):
        name = event_name(event)
        print(f"[UFC/DWCS {event_index}/{len(events)}] {name}")
        if not should_refresh_listing(args, "espn_ufc", event):
            provider_counts["events_skipped_fresh"] += 1
            print("  FRESH — unchanged distant card checked within three days")
            continue
        try:
            fightcenter = client.get_fightcenter(str(event["id"]))
            fights = event_fights(event, fightcenter)
            summary["fights_seen"] += len(fights)
            provider_counts["fights"] += len(fights)

            event_result = retry_database_operation(
                lambda: importer.import_event(
                    event=event,
                    dry_run=args.dry_run,
                ),
                f"event {name}",
            )
        except EspnMmaNoFightCardError:
            provider_counts["cardless_events_skipped"] += 1
            mark_listing_refreshed(args, "espn_ufc", event)
            print("  CARDLESS LISTING SKIPPED — no ESPN fight competitions")
            continue
        except Exception as error:
            provider_counts["event_errors"] += 1
            add_error(
                summary,
                stage="espn_ufc_event_sync",
                message=str(error),
                context=name,
            )
            print(f"  UFC/DWCS EVENT FAILED — {error}")
            continue
        if event_result["status"] == "imported":
            summary["events_imported"] += 1
        elif event_result["status"] == "updated":
            summary["events_updated"] += 1

        if args.dry_run:
            for fight in fights:
                if normalized_status(fight) in OFFICIAL_RESULT_STATUSES:
                    summary["official_results_found"] += 1
                    provider_counts["results"] += 1
            target = event_result.get("event_id") or "new row"
            print(
                "  DRY RUN — "
                f"{event_result.get('action', 'review')} {target}; "
                f"found {len(fights)} fights"
            )
            continue

        event_id = int(event_result["event_id"])
        active_fight_ids: list[int] = []
        event_fight_errors_before = provider_counts["fight_errors"]
        card_has_placeholder = False
        for fight_order, fight in enumerate(fights, start=1):
            matchup = espn_matchup_label(fight)
            try:
                fight_result = retry_database_operation(
                    lambda: importer.import_fight(
                        event_id=event_id,
                        fight=fight,
                        fight_order=fight_order,
                    ),
                    f"fight {matchup}",
                )
                if fight_result["status"] == "imported":
                    summary["fights_imported"] += 1
                elif fight_result["status"] == "updated":
                    summary["fights_updated"] += 1
                elif fight_result["status"] == "skipped_placeholder":
                    provider_counts["placeholder_fights_skipped"] += 1
                    card_has_placeholder = True
                    print(f"  PLACEHOLDER SKIPPED — {matchup}")

                if fight_result.get("fight_id") is not None:
                    active_fight_ids.append(int(fight_result["fight_id"]))

                if fight_result["fight_status"] in OFFICIAL_RESULT_STATUSES:
                    summary["official_results_found"] += 1
                    provider_counts["results"] += 1
            except Exception as error:
                provider_counts["fight_errors"] += 1
                add_error(
                    summary,
                    stage="espn_ufc_fight_sync",
                    message=str(error),
                    context=f"{name}: {matchup}",
                )
                print(f"  UFC/DWCS FIGHT FAILED — {matchup}: {error}")

        if (
            active_fight_ids
            and not card_has_placeholder
            and provider_counts["fight_errors"] == event_fight_errors_before
        ):
            archived = archive_upcoming_card_changes(
                event, today, event_id, active_fight_ids
            )
            provider_counts["card_changes_archived"] += len(archived)
            if archived:
                print(f"  CARD CHANGES — archived {len(archived)} removed matchup(s)")
        mark_listing_refreshed(args, "espn_ufc", event)

    provider_counts["requests"] = client.request_count
    provider_counts["source"] = client.event_source
    provider_counts["fightcenter_fallbacks"] = (
        client.fightcenter_fallbacks
    )
    provider_run.update(provider_counts)
    provider_run["status"] = (
        "partial"
        if provider_counts["event_errors"] or provider_counts["fight_errors"]
        else "completed"
    )
    summary["providers"]["ufc"] = "automatic"
    summary["providers"]["dwcs"] = "automatic"


def sync_pfl(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    provider_run = summary["provider_runs"]["espn_mma"]

    if args.skip_pfl:
        provider_run["status"] = "skipped"
        return

    client = EspnMmaClient(league="pfl")
    provider_run["status"] = "running"
    today = date.today()
    window_start = today - timedelta(days=args.past_days)
    window_end = today + timedelta(days=args.future_days)
    all_events = client.get_events_in_window(window_start, window_end)
    events = [
        event
        for event in all_events
        if event_in_window(event, window_start, window_end)
    ]
    events.sort(key=lambda event: (event.get("date") or "", event_name(event)))
    importer = PflImporter(supabase)

    summary["events_seen"] += len(all_events)
    summary["events_in_window"] += len(events)

    provider_counts = {
        "events": len(events),
        "fights": 0,
        "results": 0,
        "requests": 0,
        "event_errors": 0,
        "fight_errors": 0,
        "events_skipped_fresh": 0,
        "cardless_events_skipped": 0,
        "card_changes_archived": 0,
    }

    print(
        "\nESPN PFL events in sync window: "
        f"{len(events)} of {len(all_events)} "
        f"(source: {client.event_source})\n"
    )

    for event_index, event in enumerate(events, start=1):
        name = event_name(event)
        print(f"[PFL {event_index}/{len(events)}] {name}")
        if not should_refresh_listing(args, "espn_pfl", event):
            provider_counts["events_skipped_fresh"] += 1
            print("  FRESH — unchanged distant card checked within three days")
            continue
        try:
            fightcenter = client.get_fightcenter(str(event["id"]))
            fights = event_fights(event, fightcenter)
            summary["fights_seen"] += len(fights)
            provider_counts["fights"] += len(fights)
            event_result = importer.import_event(
                event=event,
                dry_run=args.dry_run,
            )
        except EspnMmaNoFightCardError:
            provider_counts["cardless_events_skipped"] += 1
            mark_listing_refreshed(args, "espn_pfl", event)
            print("  CARDLESS LISTING SKIPPED — no ESPN fight competitions")
            continue
        except Exception as error:
            provider_counts["event_errors"] += 1
            add_error(
                summary,
                stage="espn_pfl_event_sync",
                message=str(error),
                context=name,
            )
            print(f"  PFL EVENT FAILED — {error}")
            continue

        if event_result["status"] == "imported":
            summary["events_imported"] += 1
        elif event_result["status"] == "updated":
            summary["events_updated"] += 1

        if args.dry_run:
            for fight in fights:
                if normalized_status(fight) in OFFICIAL_RESULT_STATUSES:
                    summary["official_results_found"] += 1
                    provider_counts["results"] += 1
            print(f"  DRY RUN — found {len(fights)} fights")
            continue

        event_id = int(event_result["event_id"])
        active_fight_ids: list[int] = []
        event_fight_errors_before = provider_counts["fight_errors"]
        for fight_order, fight in enumerate(fights, start=1):
            matchup = espn_matchup_label(fight)
            try:
                fight_result = importer.import_fight(
                    event_id=event_id,
                    fight=fight,
                    fight_order=fight_order,
                )
                if fight_result["status"] == "imported":
                    summary["fights_imported"] += 1
                elif fight_result["status"] == "updated":
                    summary["fights_updated"] += 1
                if fight_result.get("fight_id") is not None:
                    active_fight_ids.append(int(fight_result["fight_id"]))
                if fight_result["fight_status"] in OFFICIAL_RESULT_STATUSES:
                    summary["official_results_found"] += 1
                    provider_counts["results"] += 1
            except Exception as error:
                provider_counts["fight_errors"] += 1
                add_error(
                    summary,
                    stage="espn_pfl_fight_sync",
                    message=str(error),
                    context=f"{name}: {matchup}",
                )
                print(f"  PFL FIGHT FAILED — {matchup}: {error}")

        if (
            active_fight_ids
            and provider_counts["fight_errors"] == event_fight_errors_before
        ):
            archived = archive_upcoming_card_changes(
                event, today, event_id, active_fight_ids
            )
            provider_counts["card_changes_archived"] += len(archived)
            if archived:
                print(f"  CARD CHANGES — archived {len(archived)} removed matchup(s)")
        mark_listing_refreshed(args, "espn_pfl", event)

    provider_counts["requests"] = client.request_count
    provider_counts["source"] = client.event_source
    provider_counts["fightcenter_fallbacks"] = (
        client.fightcenter_fallbacks
    )
    provider_run.update(provider_counts)
    provider_run["status"] = (
        "partial"
        if provider_counts["event_errors"] or provider_counts["fight_errors"]
        else "completed"
    )
    summary["providers"]["pfl"] = "automatic"


def sync_one(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    provider_run = summary["provider_runs"]["one_championship"]

    if args.skip_one:
        provider_run["status"] = "skipped"
        return

    client = OneChampionshipClient()
    provider_run["status"] = "running"
    today = date.today()
    window_start = today - timedelta(days=args.past_days)
    window_end = today + timedelta(days=args.future_days)
    listing_html = client.get_event_listing()
    all_events = parse_one_event_listing(listing_html)
    events = [
        event
        for event in all_events
        if one_event_in_window(event, window_start, window_end)
    ]
    events.sort(
        key=lambda event: (event.get("date") or "", one_event_name(event))
    )
    importer = OneChampionshipImporter(supabase)

    summary["events_seen"] += len(all_events)
    summary["events_in_window"] += len(events)
    provider_counts = {
        "events": len(events),
        "fights": 0,
        "results": 0,
        "requests": 0,
        "event_errors": 0,
        "events_skipped_fresh": 0,
        "card_changes_archived": 0,
    }

    print(
        "\nOfficial ONE events in sync window: "
        f"{len(events)} of {len(all_events)}\n"
    )

    for event_index, listed_event in enumerate(events, start=1):
        name = one_event_name(listed_event)
        print(f"[ONE {event_index}/{len(events)}] {name}")
        if not should_refresh_listing(args, "one", listed_event):
            provider_counts["events_skipped_fresh"] += 1
            print("  FRESH — unchanged distant card checked within three days")
            continue
        try:
            event_html = client.get_event_page(listed_event["external_url"])
            status_payload = None
            status_url = one_event_status_url(event_html)
            if (
                status_url
                and listed_event.get("date")
                and one_dashboard_event_date(listed_event) <= today
            ):
                status_payload = client.get_event_status(status_url)
            event = enrich_one_event(
                listed_event,
                event_html,
                status_payload=status_payload,
            )
            fights = parse_one_fights(event, event_html)
            summary["fights_seen"] += len(fights)
            provider_counts["fights"] += len(fights)

            event_result = importer.import_event(
                event=event,
                dry_run=args.dry_run,
            )
            if event_result["status"] == "imported":
                summary["events_imported"] += 1
            elif event_result["status"] == "updated":
                summary["events_updated"] += 1

            if args.dry_run:
                for fight in fights:
                    if one_normalized_status(fight) in OFFICIAL_RESULT_STATUSES:
                        summary["official_results_found"] += 1
                        provider_counts["results"] += 1
                print(f"  DRY RUN — found {len(fights)} fights")
                continue

            event_id = int(event_result["event_id"])
            active_fight_ids: list[int] = []
            for fight_order, fight in enumerate(fights, start=1):
                fight_result = importer.import_fight(
                    event_id=event_id,
                    fight=fight,
                    fight_order=fight.get("official_order") or fight_order,
                )
                if fight_result["status"] == "imported":
                    summary["fights_imported"] += 1
                elif fight_result["status"] == "updated":
                    summary["fights_updated"] += 1
                if fight_result.get("fight_id") is not None:
                    active_fight_ids.append(int(fight_result["fight_id"]))

                if fight_result["fight_status"] in OFFICIAL_RESULT_STATUSES:
                    summary["official_results_found"] += 1
                    provider_counts["results"] += 1
            archived = archive_upcoming_card_changes(
                event, today, event_id, active_fight_ids
            )
            provider_counts["card_changes_archived"] += len(archived)
            if archived:
                print(f"  CARD CHANGES — archived {len(archived)} removed matchup(s)")
            mark_listing_refreshed(args, "one", listed_event)
        except Exception as error:
            provider_counts["event_errors"] += 1
            add_error(
                summary,
                stage="one_event_sync",
                message=str(error),
                context=name,
            )
            print(f"  ONE EVENT FAILED — {error}")

    provider_counts["requests"] = client.request_count
    provider_run.update(provider_counts)
    if provider_counts["event_errors"]:
        provider_run["status"] = "failed"
        summary["providers"]["one"] = "failed"
    else:
        provider_run["status"] = "completed"
        summary["providers"]["one"] = "automatic"


def sync_lfa(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    provider_run = summary["provider_runs"]["lfa"]

    if args.skip_lfa:
        provider_run["status"] = "skipped"
        return

    client = LfaClient()
    provider_run["status"] = "running"
    today = date.today()
    window_start = today - timedelta(days=args.past_days)
    window_end = today + timedelta(days=args.future_days)

    official_upcoming = parse_lfa_official_events(
        client.get_official_upcoming(),
        status="upcoming",
    )
    official_past = parse_lfa_official_events(
        client.get_official_past(),
        status="completed",
    )
    sherdog_events = parse_lfa_sherdog_index(client.get_sherdog_index())
    all_events = merge_lfa_event_listings(
        [*official_upcoming, *official_past],
        sherdog_events,
    )
    events = [
        event
        for event in all_events
        if lfa_event_in_window(event, window_start, window_end)
    ]
    events.sort(
        key=lambda event: (event.get("date") or "", lfa_event_name(event))
    )
    importer = LfaImporter(supabase)

    summary["events_seen"] += len(all_events)
    summary["events_in_window"] += len(events)
    provider_counts = {
        "events": len(events),
        "fights": 0,
        "results": 0,
        "requests": 0,
        "event_errors": 0,
        "events_awaiting_card": 0,
        "events_skipped_fresh": 0,
        "card_changes_archived": 0,
    }

    print(
        "\nLFA events in sync window: "
        f"{len(events)} of {len(all_events)}\n"
    )

    for event_index, event in enumerate(events, start=1):
        name = lfa_event_name(event)
        print(f"[LFA {event_index}/{len(events)}] {name}")
        if not should_refresh_listing(args, "lfa", event):
            provider_counts["events_skipped_fresh"] += 1
            print("  FRESH — unchanged distant card checked within three days")
            continue
        try:
            fights: list[dict[str, Any]] = []
            event_page_url = lfa_sherdog_event_url(event)
            if event_page_url:
                event_html = client.get_sherdog_event(event_page_url)
                fights = parse_lfa_fights(event, event_html)
            else:
                provider_counts["events_awaiting_card"] += 1
                print("  CARD PENDING — no published Sherdog card yet")

            summary["fights_seen"] += len(fights)
            provider_counts["fights"] += len(fights)
            event_result = importer.import_event(
                event=event,
                dry_run=args.dry_run,
            )
            if event_result["status"] == "imported":
                summary["events_imported"] += 1
            elif event_result["status"] == "updated":
                summary["events_updated"] += 1

            if args.dry_run:
                for fight in fights:
                    if lfa_normalized_status(fight) in OFFICIAL_RESULT_STATUSES:
                        summary["official_results_found"] += 1
                        provider_counts["results"] += 1
                print(f"  DRY RUN — found {len(fights)} fights")
                continue

            event_id = int(event_result["event_id"])
            active_fight_ids: list[int] = []
            for fight_order, fight in enumerate(fights, start=1):
                fight_result = importer.import_fight(
                    event_id=event_id,
                    fight=fight,
                    fight_order=fight_order,
                )
                if fight_result["status"] == "imported":
                    summary["fights_imported"] += 1
                elif fight_result["status"] == "updated":
                    summary["fights_updated"] += 1
                if fight_result.get("fight_id") is not None:
                    active_fight_ids.append(int(fight_result["fight_id"]))

                if fight_result["fight_status"] in OFFICIAL_RESULT_STATUSES:
                    summary["official_results_found"] += 1
                    provider_counts["results"] += 1
            archived = archive_upcoming_card_changes(
                event, today, event_id, active_fight_ids
            )
            provider_counts["card_changes_archived"] += len(archived)
            if archived:
                print(f"  CARD CHANGES — archived {len(archived)} removed matchup(s)")
            mark_listing_refreshed(args, "lfa", event)
        except Exception as error:
            provider_counts["event_errors"] += 1
            add_error(
                summary,
                stage="lfa_event_sync",
                message=str(error),
                context=name,
            )
            print(f"  LFA EVENT FAILED — {error}")

    provider_counts["requests"] = client.request_count
    provider_run.update(provider_counts)
    if provider_counts["event_errors"]:
        provider_run["status"] = "failed"
        summary["providers"]["lfa"] = "failed"
    else:
        provider_run["status"] = "completed"
        summary["providers"]["lfa"] = "automatic"


def sync_bkfc(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    provider_run = summary["provider_runs"]["bkfc"]

    if args.skip_bkfc:
        provider_run["status"] = "skipped"
        return

    client = BkfcClient()
    provider_run["status"] = "running"
    today = date.today()
    window_start = today - timedelta(days=args.past_days)
    window_end = today + timedelta(days=args.future_days)
    upcoming = parse_bkfc_event_listing(
        client.get_upcoming(), status="upcoming"
    )
    past = parse_bkfc_event_listing(
        client.get_past(), status="completed"
    )
    all_events = merge_bkfc_event_listings(upcoming, past)
    events = [
        event
        for event in all_events
        if bkfc_event_in_window(event, window_start, window_end)
    ]
    events.sort(
        key=lambda event: (event.get("date") or "", bkfc_event_name(event))
    )
    importer = BkfcImporter(supabase)

    summary["events_seen"] += len(all_events)
    summary["events_in_window"] += len(events)
    provider_counts = {
        "events": len(events),
        "fights": 0,
        "results": 0,
        "requests": 0,
        "event_errors": 0,
        "events_awaiting_card": 0,
        "events_with_official_stats": 0,
        "stats_warnings": 0,
        "events_skipped_fresh": 0,
        "card_changes_archived": 0,
    }

    print(
        "\nOfficial BKFC events in sync window: "
        f"{len(events)} of {len(all_events)}\n"
    )

    for event_index, listed_event in enumerate(events, start=1):
        name = bkfc_event_name(listed_event)
        print(f"[BKFC {event_index}/{len(events)}] {name}")
        if not should_refresh_listing(args, "bkfc", listed_event):
            provider_counts["events_skipped_fresh"] += 1
            print("  FRESH — unchanged distant card checked within three days")
            continue
        try:
            event_html = client.get_event_page(listed_event["external_url"])
            event = enrich_bkfc_event(listed_event, event_html)
            stats_payload = None
            stats_url = bkfc_event_stats_url(event_html)
            if stats_url:
                try:
                    stats_payload = client.get_event_stats(stats_url)
                    provider_counts["events_with_official_stats"] += 1
                except BkfcProviderError as stats_error:
                    provider_counts["stats_warnings"] += 1
                    print(
                        "  STATS UNAVAILABLE — importing the card without "
                        f"optional official stats ({stats_error})"
                    )
            fights = parse_bkfc_fights(
                event,
                event_html,
                stats_payload=stats_payload,
            )
            if not fights:
                provider_counts["events_awaiting_card"] += 1
                print("  CARD PENDING — no published BKFC bouts yet")

            summary["fights_seen"] += len(fights)
            provider_counts["fights"] += len(fights)
            event_result = importer.import_event(
                event=event,
                dry_run=args.dry_run,
            )
            if event_result["status"] == "imported":
                summary["events_imported"] += 1
            elif event_result["status"] == "updated":
                summary["events_updated"] += 1

            if args.dry_run:
                for fight in fights:
                    if bkfc_normalized_status(fight) in OFFICIAL_RESULT_STATUSES:
                        summary["official_results_found"] += 1
                        provider_counts["results"] += 1
                print(f"  DRY RUN — found {len(fights)} fights")
                continue

            event_id = int(event_result["event_id"])
            active_fight_ids: list[int] = []
            for fight_order, fight in enumerate(fights, start=1):
                fight_result = importer.import_fight(
                    event_id=event_id,
                    fight=fight,
                    fight_order=fight_order,
                )
                if fight_result["status"] == "imported":
                    summary["fights_imported"] += 1
                elif fight_result["status"] == "updated":
                    summary["fights_updated"] += 1
                if fight_result.get("fight_id") is not None:
                    active_fight_ids.append(int(fight_result["fight_id"]))

                if fight_result["fight_status"] in OFFICIAL_RESULT_STATUSES:
                    summary["official_results_found"] += 1
                    provider_counts["results"] += 1
            archived = archive_upcoming_card_changes(
                event, today, event_id, active_fight_ids
            )
            provider_counts["card_changes_archived"] += len(archived)
            if archived:
                print(f"  CARD CHANGES — archived {len(archived)} removed matchup(s)")
            mark_listing_refreshed(args, "bkfc", listed_event)
        except Exception as error:
            provider_counts["event_errors"] += 1
            add_error(
                summary,
                stage="bkfc_event_sync",
                message=str(error),
                context=name,
            )
            print(f"  BKFC EVENT FAILED — {error}")

    provider_counts["requests"] = client.request_count
    provider_run.update(provider_counts)
    if provider_counts["event_errors"]:
        provider_run["status"] = "failed"
        summary["providers"]["bkfc"] = "failed"
    else:
        provider_run["status"] = "completed"
        summary["providers"]["bkfc"] = "automatic"


def run_catalog_sync(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    try:
        metrics = sync_official_catalogs(
            supabase,
            requested_scope=args.requested_scope,
            dry_run=args.dry_run,
            past_days=max(args.past_days, 30),
            future_days=max(args.future_days, 90),
        )
        summary["provider_runs"]["official_catalog"] = metrics
        summary["catalog_issues"] = metrics.get("issues") or []
        for catalog, row in (metrics.get("catalogs") or {}).items():
            print(
                f"Official {catalog.upper()} catalog — "
                f"{row.get('events', 0)} events, "
                f"{row.get('imported', 0)} repaired, "
                f"{row.get('failures', 0)} issue(s)."
            )
    except Exception as error:
        summary["provider_runs"]["official_catalog"] = {
            "status": "failed",
            "message": str(error),
            "catalogs": {},
        }
        summary["catalog_issues"] = [{
            "code": "CATALOG_UNAVAILABLE",
            "severity": "warning",
            "promotion": (
                args.requested_scope.upper()
                if args.requested_scope != "all"
                else "UFC / DWCS / PFL"
            ),
            "message": str(error),
        }]
        summary["warnings"].append({
            "stage": "official_event_catalog",
            "message": str(error),
        })
        print("\nOFFICIAL EVENT CATALOG ISSUE — " + str(error))


def run_odds_import(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    if args.skip_odds:
        summary["odds_status"] = "skipped"
        summary["provider_runs"]["the_odds_api"]["status"] = "skipped"
        summary["provider_runs"]["api_sports_mma"]["status"] = "skipped"
        summary["provider_runs"]["fightodds"]["status"] = "skipped"
        return

    has_primary = bool(os.getenv("THE_ODDS_API_KEY"))
    _fallback_key, fallback_key_environment = resolve_api_sports_key()
    has_fallback = bool(_fallback_key)
    if not has_primary and not has_fallback:
        summary["provider_runs"]["the_odds_api"]["status"] = "skipped_missing_key"
        summary["provider_runs"]["api_sports_mma"] = {
            "status": "skipped_missing_key",
            "accepted_key_names": list(API_SPORTS_KEY_NAMES),
            "env_files_checked": [str(path) for path in API_SPORTS_ENV_PATHS],
        }
        print("\nKeyed odds providers skipped — no API key is configured.")

    child_environment = os.environ.copy()
    child_environment.update({
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })
    successful_provider = False
    if has_primary:
        result = subprocess.run(
            [sys.executable, str(ODDS_IMPORTER)], cwd=str(ODDS_IMPORTER.parent),
            env=child_environment, capture_output=True, text=True,
            encoding="utf-8", errors="backslashreplace", check=False,
        )
        if result.stdout:
            print("\n" + result.stdout.rstrip())
        metrics = {}
        for line in (result.stdout or "").splitlines():
            if line.startswith("ODDS_IMPORT_SUMMARY="):
                try:
                    metrics = json.loads(line.split("=", 1)[1])
                except json.JSONDecodeError:
                    pass
        metrics["status"] = "failed" if result.returncode else metrics.get("status", "completed")
        summary["provider_runs"]["the_odds_api"] = metrics
        if result.returncode:
            message = result.stderr.strip() or f"Odds importer exited with code {result.returncode}."
            summary["warnings"].append({"stage": "the_odds_api", "message": message})
            print("\nPRIMARY ODDS IMPORT ISSUE — " + message)
        else:
            successful_provider = True
    else:
        summary["provider_runs"]["the_odds_api"]["status"] = "skipped_missing_key"

    if has_fallback:
        try:
            from providers.api_sports_mma.import_current_odds import import_api_sports_odds
            metrics = import_api_sports_odds()
            metrics.setdefault("key_environment", fallback_key_environment)
            summary["provider_runs"]["api_sports_mma"] = metrics
            successful_provider = successful_provider or metrics.get("status") in {
                "completed", "completed_limited", "partial"
            }
            print(
                "\nAPI-Sports fallback — "
                f"{metrics.get('matched', 0)} matched, {metrics.get('inserted', 0)} new prices, "
                f"{metrics.get('requests', 0)} requests."
            )
        except Exception as error:
            summary["provider_runs"]["api_sports_mma"] = {"status": "failed", "message": str(error)}
            summary["warnings"].append({"stage": "api_sports_mma", "message": str(error)})
            print("\nAPI-SPORTS ODDS FALLBACK ISSUE — " + str(error))
    else:
        summary["provider_runs"]["api_sports_mma"] = {
            "status": "skipped_missing_key",
            "accepted_key_names": list(API_SPORTS_KEY_NAMES),
            "env_files_checked": [str(path) for path in API_SPORTS_ENV_PATHS],
        }

    try:
        pre_fallback_audit = audit_upcoming_coverage(supabase)
        from providers.fightodds.import_current_odds import import_fightodds_odds
        fightodds_metrics = import_fightodds_odds(
            pre_fallback_audit.get("cards") or []
        )
        summary["provider_runs"]["fightodds"] = fightodds_metrics
        successful_provider = successful_provider or fightodds_metrics.get("status") in {
            "completed", "partial", "skipped_no_gaps"
        }
        print(
            "\nFightOdds public fallback — "
            f"{fightodds_metrics.get('matched', 0)} matched, "
            f"{fightodds_metrics.get('inserted', 0)} new prices, "
            f"{fightodds_metrics.get('requests', 0)} pages."
        )
    except Exception as error:
        summary["provider_runs"]["fightodds"] = {"status": "failed", "message": str(error)}
        summary["warnings"].append({"stage": "fightodds", "message": str(error)})
        print("\nFIGHTODDS FALLBACK ISSUE — " + str(error))

    summary["odds_status"] = "completed" if successful_provider else "failed"


def run_lightweight_history_check(args: argparse.Namespace, summary: dict[str, Any]) -> None:
    if args.dry_run:
        summary["history_check"] = {"status": "skipped_dry_run"}
        return
    command = [
        sys.executable, str(API_ROOT / "sync" / "history_maintenance.py"),
        "--skip-provider-refresh", "--due-only", "--max-fighters", "8",
    ]
    result = subprocess.run(
        command, cwd=PROJECT_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="backslashreplace", check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    summary["history_check"] = {
        "status": "completed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
    }
    if result.returncode:
        summary["warnings"].append({
            "stage": "fighter_history_check",
            "message": (result.stderr or result.stdout or "History check failed.")[-1200:],
        })


def run_quality_audit(summary: dict[str, Any]) -> None:
    try:
        summary["quality_audit"] = audit_upcoming_coverage(supabase)
        catalog_issues = summary.get("catalog_issues") or []
        if catalog_issues:
            summary["quality_audit"]["issues"] = [
                *catalog_issues,
                *(summary["quality_audit"].get("issues") or []),
            ]
            summary["quality_audit"]["status"] = "gaps_found"
        expected = summary["quality_audit"]["odds"]["expected_fights"]
        covered = summary["quality_audit"]["odds"]["covered_fights"]
        if summary["odds_status"] == "completed" and expected and covered < expected:
            summary["odds_status"] = "completed_with_gaps"
    except Exception as error:
        summary["quality_audit"] = {"status": "failed", "issues": [], "message": str(error)}
        summary["warnings"].append({"stage": "coverage_audit", "message": str(error)})


def write_local_report(summary: dict[str, Any]) -> Path:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    report_path = REPORTS_ROOT / f"sync_{timestamp}.json"
    report_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report_path


def start_sync_run(summary: dict[str, Any]) -> int | None:
    if summary.get("dry_run") or summary.get("no_dashboard_status"):
        return None
    record = {
        "started_at": summary["started_at"],
        "finished_at": None,
        "status": "running",
        "events_processed": 0,
        "fights_processed": 0,
        "results_processed": 0,
        "odds_status": "not_run",
        "summary": {
            "status": "running",
            "run_mode": summary.get("run_mode"),
            "requested_scope": summary.get("requested_scope"),
            "window": summary.get("window"),
        },
    }
    try:
        response = supabase.table("data_sync_runs").insert(record).execute()
        return int(response.data[0]["data_sync_run_id"]) if response.data else None
    except Exception as error:
        print(f"\nWARNING — running sync status could not be saved: {error}")
        return None


def save_sync_run(summary: dict[str, Any], run_id: int | None = None) -> None:
    if summary.get("dry_run") or summary.get("no_dashboard_status"):
        return

    record = {
        "started_at": summary["started_at"],
        "finished_at": summary["finished_at"],
        "status": summary["status"],
        "events_processed": summary["events_in_window"],
        "fights_processed": (
            summary["fights_imported"]
            + summary["fights_updated"]
        ),
        "results_processed": summary["official_results_found"],
        "odds_status": summary["odds_status"],
        "summary": summary,
    }

    try:
        if run_id is None:
            supabase.table("data_sync_runs").insert(record).execute()
        else:
            response = (
                supabase.table("data_sync_runs")
                .update(record)
                .eq("data_sync_run_id", run_id)
                .execute()
            )
            if not response.data:
                raise RuntimeError("Running sync row was not found at completion.")
    except Exception as error:
        print(
            "\nWARNING — sync finished, but its dashboard status "
            f"could not be saved: {error}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Sync UFC/DWCS cards from ESPN MMA, enrich them from "
            "UFCStats, sync PFL from ESPN MMA, "
            "ONE from ONE Championship, "
            "LFA from LFA/Sherdog, "
            "BKFC from BKFC/MMAReg, "
            "then import current MMA moneylines when configured."
        )
    )
    parser.add_argument(
        "--mode",
        choices=("daily", "maintenance", "repair"),
        default="daily",
        help="Daily is the fast card/odds path; maintenance and repair are manual/weekly.",
    )
    parser.add_argument("--past-days", type=int, default=2)
    parser.add_argument("--future-days", type=int, default=21)
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument(
        "--stats-refresh-days",
        type=int,
        default=1,
        help=(
            "Recheck already-completed UFCStats fights this many days after "
            "the event. Older complete fights are skipped."
        ),
    )
    parser.add_argument(
        "--full-repair",
        action="store_true",
        help="Force UFCStats to rebuild every completed fight in the window.",
    )
    parser.add_argument("--skip-retention", action="store_true")
    parser.add_argument("--skip-catalog", action="store_true")
    parser.add_argument("--skip-odds", action="store_true")
    parser.add_argument("--skip-stats", action="store_true")
    parser.add_argument("--skip-ufc", action="store_true")
    parser.add_argument("--skip-ufcstats", action="store_true")
    parser.add_argument("--skip-pfl", action="store_true")
    parser.add_argument("--skip-one", action="store_true")
    parser.add_argument("--skip-lfa", action="store_true")
    parser.add_argument("--skip-bkfc", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--requested-scope",
        default="all",
        choices=("all", "ufc", "dwcs", "pfl", "one", "lfa", "bkfc"),
        help="Dashboard-requested refresh scope, stored for truthful status labels.",
    )
    parser.add_argument(
        "--no-dashboard-status",
        action="store_true",
        help=(
            "Write a local report but do not replace the dashboard's latest "
            "daily refresh status. Used by periodic history maintenance."
        ),
    )
    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="Show Chromium while UFCStats pages are being read.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "daily":
        # Current cards/results already come from each promotion adapter. Slow
        # browser-based historical/stat enrichment belongs to maintenance.
        args.skip_ufcstats = True
        args.skip_stats = True
    args.freshness_cache = EventFreshnessCache(FRESHNESS_STATE)
    summary = empty_summary(args)
    summary["no_dashboard_status"] = args.no_dashboard_status
    run_id = start_sync_run(summary)

    print("=" * 64)
    print("MMA DASHBOARD DATA SYNC")
    print(
        f"Window: {args.past_days} days back / "
        f"{args.future_days} days forward"
    )
    print(f"Mode: {args.mode}")
    print(
        "UFCStats: "
        + (
            "deferred to maintenance"
            if args.skip_ufcstats
            else "full repair"
            if args.full_repair
            else f"incremental ({args.stats_refresh_days}-day refresh)"
        )
    )
    print("=" * 64)

    if args.skip_catalog:
        summary["provider_runs"]["official_catalog"]["status"] = "skipped"
    else:
        timed_stage(
            summary,
            "official_catalog",
            "Checking official UFC, DWCS and PFL schedules",
            lambda: run_catalog_sync(args, summary),
        )

    try:
        timed_stage(
            summary,
            "ufc_dwcs",
            "Refreshing UFC and DWCS cards",
            lambda: sync_ufc(args, summary),
        )
    except Exception as error:
        summary["provider_runs"]["espn_ufc"]["status"] = "failed"
        summary["providers"]["ufc"] = "failed"
        summary["providers"]["dwcs"] = "failed"
        add_error(
            summary,
            stage="espn_ufc_sync",
            message=str(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nESPN UFC/DWCS SYNC FAILED — " + str(error))

    if args.skip_ufc or args.skip_ufcstats:
        summary["provider_runs"]["ufcstats"]["status"] = "skipped"
    else:
        try:
            timed_stage(
                summary,
                "ufcstats",
                "Enriching completed UFC fights",
                lambda: sync_ufcstats(args, summary),
            )
        except Exception as error:
            summary["provider_runs"]["ufcstats"]["status"] = "failed"
            add_error(
                summary,
                stage="ufcstats_sync",
                message=str(error),
                context=traceback.format_exc(limit=5),
            )
            print("\nUFCSTATS SYNC FAILED — " + str(error))

    try:
        timed_stage(
            summary,
            "pfl",
            "Refreshing PFL cards",
            lambda: sync_pfl(args, summary),
        )
    except Exception as error:
        summary["provider_runs"]["espn_mma"]["status"] = "failed"
        summary["providers"]["pfl"] = "failed"
        add_error(
            summary,
            stage="pfl_sync",
            message=str(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nPFL SYNC FAILED — " + str(error))

    try:
        timed_stage(
            summary,
            "one",
            "Refreshing ONE cards",
            lambda: sync_one(args, summary),
        )
    except Exception as error:
        summary["provider_runs"]["one_championship"]["status"] = "failed"
        summary["providers"]["one"] = "failed"
        add_error(
            summary,
            stage="one_sync",
            message=str(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nONE SYNC FAILED — " + str(error))

    try:
        timed_stage(
            summary,
            "lfa",
            "Refreshing LFA cards",
            lambda: sync_lfa(args, summary),
        )
    except Exception as error:
        summary["provider_runs"]["lfa"]["status"] = "failed"
        summary["providers"]["lfa"] = "failed"
        add_error(
            summary,
            stage="lfa_sync",
            message=str(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nLFA SYNC FAILED — " + str(error))

    try:
        timed_stage(
            summary,
            "bkfc",
            "Refreshing BKFC cards",
            lambda: sync_bkfc(args, summary),
        )
    except Exception as error:
        summary["provider_runs"]["bkfc"]["status"] = "failed"
        summary["providers"]["bkfc"] = "failed"
        add_error(
            summary,
            stage="bkfc_sync",
            message=str(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nBKFC SYNC FAILED — " + str(error))

    try:
        timed_stage(
            summary,
            "odds",
            "Refreshing current moneylines",
            lambda: run_odds_import(args, summary),
        )
    except Exception as error:
        add_error(
            summary,
            stage="odds_sync",
            message=str(error),
            context=traceback.format_exc(limit=5),
        )
        summary["odds_status"] = "failed"
        print("\nODDS SYNC FAILED — " + str(error))

    summary["history_check"] = {"status": "deferred_to_weekly_maintenance"}
    timed_stage(
        summary,
        "coverage",
        "Validating event, card, odds and history coverage",
        lambda: run_quality_audit(summary),
    )
    try:
        args.freshness_cache.save()
    except OSError as error:
        summary["warnings"].append({
            "stage": "freshness_cache",
            "message": f"Refresh cache could not be saved: {error}",
        })

    summary["finished_at"] = utc_now()
    if not summary["errors"]:
        summary["status"] = "success"
    elif (
        summary["events_seen"] == 0
        and summary["provider_runs"]["ufcstats"]["status"] != "skipped"
    ):
        summary["status"] = "failed"
    else:
        summary["status"] = "partial"
    report_path = write_local_report(summary)
    save_sync_run(summary, run_id)

    print("\n" + "=" * 64)
    print(f"Status:             {summary['status'].upper()}")
    print(f"Events in window:   {summary['events_in_window']}")
    print(
        "Events added/updated: "
        f"{summary['events_imported']}/"
        f"{summary['events_updated']}"
    )
    print(
        "Fights added/updated: "
        f"{summary['fights_imported']}/"
        f"{summary['fights_updated']}"
    )
    print(f"Results found:      {summary['official_results_found']}")
    print(f"Stat rows:          {summary['stat_rows_processed']}")
    ufcstats_run = summary["provider_runs"]["ufcstats"]
    if ufcstats_run.get("status") == "completed":
        print(
            "UFCStats fights:    "
            f"{ufcstats_run.get('fights_refreshed', 0)} refreshed / "
            f"{ufcstats_run.get('fights_skipped_complete', 0)} "
            "already complete"
        )
    print(f"Odds:               {summary['odds_status']}")
    print("Retention:          disabled (FightCenter history preserved)")
    quality = summary.get("quality_audit") or {}
    if quality.get("odds"):
        print(
            "Odds coverage:      "
            f"{quality['odds']['covered_fights']}/{quality['odds']['expected_fights']} upcoming fights"
        )
    print(f"Errors:             {len(summary['errors'])}")
    print(f"Local report:       {report_path}")
    print("=" * 64)

    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
