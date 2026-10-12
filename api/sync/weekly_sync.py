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
from zoneinfo import ZoneInfo
from uuid import uuid4
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
from uploader import import_event, supabase, get_ufcstats_source_id
from providers.persistence import save_rows  # noqa: E402
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
from sync.cards import process_cards
from sync.lease import SyncLease, ImportBusyError
from sync.readiness import resolve_scope, finalize_readiness
from providers.errors import safe_error
from providers.event_catalog.importer import event_match_score
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
            "message": safe_error(message),
            "context": safe_error(context),
        }
    )


def sync_ufcstats(
    args: argparse.Namespace,
    summary: dict[str, Any],
) -> None:
    provider_run = summary["provider_runs"]["ufcstats"]
    provider_run["status"] = "running"
    today = datetime.now(ZoneInfo("America/Chicago")).date()
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

    state = None if args.dry_run else UfcstatsSyncState.load(supabase,get_ufcstats_source_id())

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
                    message=safe_error(error),
                    context=event_label,
                )
                print(f"  EVENT FAILED — {safe_error(error)}")
                continue

            try:
                fights = get_fights_from_event(event["url"])
                summary["fights_seen"] += len(fights)
            except Exception as error:
                add_error(
                    summary,
                    stage="fight_list",
                    message=safe_error(error),
                    context=event_label,
                )
                print(f"  FIGHT LIST FAILED — {safe_error(error)}")
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
                        message=safe_error(error),
                        context=f"{event_label}: {matchup}",
                    )
                    print(f"  FIGHT FAILED — {matchup}: {safe_error(error)}")
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
                    print(f"  STATS PENDING — {matchup}: {safe_error(error)}")
                except Exception as error:
                    add_error(
                        summary,
                        stage="stats_import",
                        message=safe_error(error),
                        context=f"{event_label}: {matchup}",
                    )
                    print(f"  STATS FAILED — {matchup}: {safe_error(error)}")

    provider_run.update(provider_counts)
    provider_run["status"] = "completed"


def sync_ufc(args, summary):
    if args.skip_ufc:
        summary["provider_runs"]["espn_ufc"]["status"] = "skipped"
        return
    client = EspnMmaClient(league="ufc")
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    start, end = today-timedelta(days=args.past_days), today+timedelta(days=args.future_days)
    all_events = client.get_events_in_window(start, end)
    expected = [row for row in (summary["provider_runs"].get("official_catalog", {}).get("entries") or [])
                if row["promotion_key"] in ("ufc", "dwcs") and start.isoformat() <= row["date"] <= end.isoformat()]
    def missing(rows):
        return [entry for entry in expected if not any(
            abs((date.fromisoformat(entry["date"])-parse_event_date(row)).days) <= 1
            and event_match_score(entry["name"], event_name(row)) >= 0.64
            for row in rows if parse_event_date(row))]
    if missing(all_events):
        try:
            supplemental = client._get_core_events(start, end)
            all_events = list({str(row["id"]): row for row in [*all_events,*supplemental]}.values())
        except Exception as error:
            summary["warnings"].append({"stage":"espn_ufc","message":safe_error(error)})
    for entry in missing(all_events):
        summary["catalog_issues"].append({"code":"DETAIL_SOURCE_GAP","severity":"warning",
            "promotion":entry["promotion_key"].upper(),"event_name":entry["name"],
            "event_date":entry["date"],"message":"Official event retained; ESPN has no matching detailed card yet."})
    events = sorted([row for row in all_events if event_in_window(row,start,end)],
                    key=lambda row:(row.get("date") or "",event_name(row)))
    def fetch(event):
        try:
            center = client.get_fightcenter(str(event["id"]))
            return event, event_fights(event,center), []
        except EspnMmaNoFightCardError:
            return event, [], ["Event retained; the source has not published a usable card."]
    process_cards(args,summary,client,UfcImporter(supabase),all_events,events,"espn_ufc",
                  ("ufc", "dwcs"),event_name,fetch,should_refresh_listing,mark_listing_refreshed)


def sync_pfl(args, summary):
    if args.skip_pfl:
        summary["provider_runs"]["espn_mma"]["status"] = "skipped"
        return
    client = EspnMmaClient(league="pfl")
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    start, end = today-timedelta(days=args.past_days), today+timedelta(days=args.future_days)
    all_events = client.get_events_in_window(start, end)
    expected = [row for row in (summary["provider_runs"].get("official_catalog", {}).get("entries") or [])
                if row["promotion_key"] in ("pfl",) and start.isoformat() <= row["date"] <= end.isoformat()]
    def missing(rows):
        return [entry for entry in expected if not any(
            abs((date.fromisoformat(entry["date"])-parse_event_date(row)).days) <= 1
            and event_match_score(entry["name"], event_name(row)) >= 0.64
            for row in rows if parse_event_date(row))]
    if missing(all_events):
        try:
            supplemental = client._get_core_events(start, end)
            all_events = list({str(row["id"]): row for row in [*all_events,*supplemental]}.values())
        except Exception as error:
            summary["warnings"].append({"stage":"espn_mma","message":safe_error(error)})
    for entry in missing(all_events):
        summary["catalog_issues"].append({"code":"DETAIL_SOURCE_GAP","severity":"warning",
            "promotion":entry["promotion_key"].upper(),"event_name":entry["name"],
            "event_date":entry["date"],"message":"Official event retained; ESPN has no matching detailed card yet."})
    events = sorted([row for row in all_events if event_in_window(row,start,end)],
                    key=lambda row:(row.get("date") or "",event_name(row)))
    def fetch(event):
        try:
            center = client.get_fightcenter(str(event["id"]))
            return event, event_fights(event,center), []
        except EspnMmaNoFightCardError:
            return event, [], ["Event retained; the source has not published a usable card."]
    process_cards(args,summary,client,PflImporter(supabase),all_events,events,"espn_mma",
                  ("pfl",),event_name,fetch,should_refresh_listing,mark_listing_refreshed)


def sync_one(args, summary):
    if args.skip_one:
        summary["provider_runs"]["one_championship"]["status"]="skipped"
        return
    client=OneChampionshipClient()
    today=datetime.now(ZoneInfo("America/Chicago")).date()
    start,end=today-timedelta(days=args.past_days),today+timedelta(days=args.future_days)
    all_events=parse_one_event_listing(client.get_event_listing())
    events=sorted([row for row in all_events if one_event_in_window(row,start,end)],key=lambda row:(row.get("date") or "",one_event_name(row)))
    def fetch(listed):
        html=client.get_event_page(listed["external_url"])
        status_url=one_event_status_url(html)
        status=client.get_event_status(status_url) if status_url and one_dashboard_event_date(listed)<=today else None
        event=enrich_one_event(listed,html,status_payload=status)
        return event,parse_one_fights(event,html),[]
    process_cards(args,summary,client,OneChampionshipImporter(supabase),all_events,events,
                  "one_championship",("one",),one_event_name,fetch,should_refresh_listing,mark_listing_refreshed)


def sync_lfa(args, summary):
    if args.skip_lfa:
        summary["provider_runs"]["lfa"]["status"]="skipped"
        return
    client=LfaClient()
    today=datetime.now(ZoneInfo("America/Chicago")).date()
    start,end=today-timedelta(days=args.past_days),today+timedelta(days=args.future_days)
    official=[*parse_lfa_official_events(client.get_official_upcoming(),status="upcoming"),
              *parse_lfa_official_events(client.get_official_past(),status="completed")]
    all_events=merge_lfa_event_listings(official,parse_lfa_sherdog_index(client.get_sherdog_index()))
    events=sorted([row for row in all_events if lfa_event_in_window(row,start,end)],key=lambda row:(row.get("date") or "",lfa_event_name(row)))
    def fetch(event):
        url=lfa_sherdog_event_url(event)
        fights=parse_lfa_fights(event,client.get_sherdog_event(url)) if url else []
        return event,fights,[] if url else ["Official event retained; no published detailed card was found."]
    process_cards(args,summary,client,LfaImporter(supabase),all_events,events,"lfa",("lfa",),
                  lfa_event_name,fetch,should_refresh_listing,mark_listing_refreshed)


def sync_bkfc(args, summary):
    if args.skip_bkfc:
        summary["provider_runs"]["bkfc"]["status"]="skipped"
        return
    client=BkfcClient()
    today=datetime.now(ZoneInfo("America/Chicago")).date()
    start,end=today-timedelta(days=args.past_days),today+timedelta(days=args.future_days)
    all_events=merge_bkfc_event_listings(parse_bkfc_event_listing(client.get_upcoming(),status="upcoming"),
                                       parse_bkfc_event_listing(client.get_past(),status="completed"))
    events=sorted([row for row in all_events if bkfc_event_in_window(row,start,end)],key=lambda row:(row.get("date") or "",bkfc_event_name(row)))
    def fetch(listed):
        html=client.get_event_page(listed["external_url"])
        event=enrich_bkfc_event(listed,html)
        stats_url=bkfc_event_stats_url(html)
        stats,warnings=None,[]
        if stats_url:
            try: stats=client.get_event_stats(stats_url)
            except BkfcProviderError as error: warnings.append(safe_error(error))
        return event,parse_bkfc_fights(event,html,stats_payload=stats),warnings
    process_cards(args,summary,client,BkfcImporter(supabase),all_events,events,"bkfc",("bkfc",),
                  bkfc_event_name,fetch,should_refresh_listing,mark_listing_refreshed)


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
            "message": safe_error(error),
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
            "message": safe_error(error),
        }]
        summary["warnings"].append({
            "stage": "official_event_catalog",
            "message": safe_error(error),
        })
        print("\nOFFICIAL EVENT CATALOG ISSUE — " + safe_error(error))


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

    skip_keyed=getattr(args,"skip_keyed_odds",False)
    has_primary = bool(os.getenv("THE_ODDS_API_KEY")) and not skip_keyed
    _fallback_key, fallback_key_environment = resolve_api_sports_key()
    has_fallback = bool(_fallback_key) and not skip_keyed
    if not has_primary and not has_fallback and not skip_keyed:
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
            print("\n" + safe_error(result.stdout).rstrip())
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
            message = safe_error(result.stderr).strip() or f"Odds importer exited with code {result.returncode}."
            summary["warnings"].append({"stage": "the_odds_api", "message": message})
            print("\nPRIMARY ODDS IMPORT ISSUE — " + message)
        else:
            successful_provider = True
    else:
        summary["provider_runs"]["the_odds_api"]["status"] = "skipped_retry_budget" if skip_keyed else "skipped_missing_key"

    gap_audit = audit_upcoming_coverage(supabase)
    gap_ids = {int(m["fight_id"]) for c in gap_audit["cards"] if c["odds_expected"] for m in c["missing_matchups"]}
    if has_fallback and gap_ids:
        try:
            from providers.api_sports_mma.import_current_odds import import_api_sports_odds
            metrics = import_api_sports_odds(target_fight_ids=gap_ids)
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
            summary["provider_runs"]["api_sports_mma"] = {"status": "failed", "message": safe_error(error)}
            summary["warnings"].append({"stage": "api_sports_mma", "message": safe_error(error)})
            print("\nAPI-SPORTS ODDS FALLBACK ISSUE — " + safe_error(error))
    else:
        summary["provider_runs"]["api_sports_mma"] = {
            "status": "skipped_retry_budget" if skip_keyed else "skipped_no_gaps" if has_fallback else "skipped_missing_key",
            "accepted_key_names": list(API_SPORTS_KEY_NAMES),
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
        summary["provider_runs"]["fightodds"] = {"status": "failed", "message": safe_error(error)}
        summary["warnings"].append({"stage": "fightodds", "message": safe_error(error)})
        print("\nFIGHTODDS FALLBACK ISSUE — " + safe_error(error))

    summary["odds_status"] = "completed" if successful_provider else "failed"


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
        summary["quality_audit"] = {"status": "failed", "issues": [], "message": safe_error(error)}
        summary["warnings"].append({"stage": "coverage_audit", "message": safe_error(error)})


def write_local_report(summary: dict[str, Any]) -> Path:
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    report_path = REPORTS_ROOT / f"sync_{timestamp}_{uuid4().hex[:8]}.json"
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
        saved = save_rows(supabase,"data_sync_runs",[record])
        if not saved:
            raise RuntimeError("Running status insert returned no row.")
        return int(saved[0]["data_sync_run_id"])
    except Exception as error:
        raise RuntimeError("Refresh could not register its running status; no imports were started.") from error


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
        if run_id is not None: record["data_sync_run_id"]=run_id
        if not save_rows(supabase,"data_sync_runs",[record]):
            raise RuntimeError("Running sync row was not found at completion.")
    except Exception as error:
        raise RuntimeError("Refresh completion could not be saved; Discord publication is withheld.") from error


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
    parser.add_argument("--skip-keyed-odds",action="store_true",help="Use existing/public prices during automatic retries without repeating paid API requests.")
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
        choices=("all", "ufc", "dwcs", "pfl", "one", "lfa", "bkfc", "odds", "custom"),
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


def execute_sync(args, summary, run_id, lease):
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
            message=safe_error(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nESPN UFC/DWCS SYNC FAILED — " + safe_error(error))

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
                message=safe_error(error),
                context=traceback.format_exc(limit=5),
            )
            print("\nUFCSTATS SYNC FAILED — " + safe_error(error))

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
            message=safe_error(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nPFL SYNC FAILED — " + safe_error(error))

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
            message=safe_error(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nONE SYNC FAILED — " + safe_error(error))

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
            message=safe_error(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nLFA SYNC FAILED — " + safe_error(error))

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
            message=safe_error(error),
            context=traceback.format_exc(limit=5),
        )
        print("\nBKFC SYNC FAILED — " + safe_error(error))

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
            message=safe_error(error),
            context=traceback.format_exc(limit=5),
        )
        summary["odds_status"] = "failed"
        print("\nODDS SYNC FAILED — " + safe_error(error))

    summary["history_check"] = {"status": "deferred_to_weekly_maintenance"}
    timed_stage(
        summary,
        "coverage",
        "Validating event, card, odds and history coverage",
        lambda: run_quality_audit(summary),
    )
    try:
        if not args.dry_run:
            args.freshness_cache.save()
    except OSError as error:
        summary["warnings"].append({
            "stage": "freshness_cache",
            "message": f"Refresh cache could not be saved: {safe_error(error)}",
        })

    summary["finished_at"] = utc_now()
    lease.ensure_owned()
    finalize_readiness(summary,args)
    save_sync_run(summary, run_id)
    try:
        report_path = write_local_report(summary)
    except OSError:
        report_path = "Local report could not be written; database status was saved."

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

    failed_catalog = not args.skip_catalog and args.requested_scope in {"all","ufc","dwcs","pfl"} and summary["provider_runs"]["official_catalog"]["status"] != "completed"
    required_cards_not_ready=args.mode=="daily" and args.requested_scope=="all" and not args.dry_run and not summary["publishable"]
    return 1 if summary["errors"] or failed_catalog or summary["quality_audit"]["status"] == "failed" or required_cards_not_ready else 0


def main() -> int:
    args=build_parser().parse_args()
    args.requested_scope=resolve_scope(args)
    if args.dry_run:
        args.skip_odds=True
    if args.mode == "daily":
        args.skip_ufcstats=True
        args.skip_stats=True
    args.freshness_cache=EventFreshnessCache(FRESHNESS_STATE)
    try:
        with SyncLease(supabase,dry_run=args.dry_run) as lease:
            summary=empty_summary(args)
            summary["no_dashboard_status"]=args.no_dashboard_status
            summary["lease_fence"]=os.environ.get("MMA_SYNC_LEASE_FENCE")
            run_id=start_sync_run(summary)
            try:
                return execute_sync(args,summary,run_id,lease)
            except BaseException as error:
                summary.update(status="failed",publishable=False,finished_at=utc_now())
                summary["errors"].append({"stage":"interrupted","message":safe_error(error)})
                save_sync_run(summary,run_id)
                raise
    except ImportBusyError as error:
        print(safe_error(error))
        return 75
    except Exception as error:
        print("Refresh stopped: "+safe_error(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
