"""Use the official card for catalog events missing from ESPN listings."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..errors import safe_error
from ..espn_mma.client import EspnMmaClient, EspnMmaNoFightCardError
from ..espn_mma.importer import PflImporter
from ..espn_mma.normalizer import dashboard_event_date, event_fights, event_name
from ..event_catalog.importer import event_match_score
try:
    from sync.cards import process_cards
    from sync.result_followup import include_followups
except ModuleNotFoundError:
    from api.sync.cards import process_cards
    from api.sync.result_followup import include_followups
from .client import OfficialPflClient
from .importer import OfficialPflImporter


def _day(event):
    try:
        return dashboard_event_date(event)
    except (ValueError, TypeError, KeyError):
        return None


def sync_pfl_cards(args, summary, supabase, should_refresh, mark_refreshed):
    client = EspnMmaClient(league="pfl")
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    start, end = today - timedelta(days=args.past_days), today + timedelta(days=args.future_days)
    catalog = summary["provider_runs"].get("official_catalog") or {}
    expected = [entry for entry in catalog.get("entries", []) if entry["promotion_key"] == "pfl"
                and start.isoformat() <= entry["date"] <= end.isoformat()]
    try:
        all_events = client.get_events_in_window(start, end)
    except Exception as error:
        all_events = []
        summary["warnings"].append({"stage": "espn_mma", "message": safe_error(error)})

    def missing(rows):
        return [entry for entry in expected if not any(_day(row) and row.get("name")
                    and abs((date.fromisoformat(entry["date"]) - _day(row)).days) <= 1
                    and event_match_score(entry["name"], event_name(row)) >= 0.64 for row in rows)]

    if missing(all_events):
        try:
            supplemental = client._get_core_events(start, end)
            all_events = list({str(row["id"]): row for row in [*all_events, *supplemental]}.values())
        except Exception as error:
            summary["warnings"].append({"stage": "espn_mma", "message": safe_error(error)})
    events = sorted([row for row in all_events if _day(row) and start <= _day(row) <= end],
                    key=lambda row: (row.get("date") or "", event_name(row)))
    all_events, events = include_followups(args, "espn_mma", all_events, events)

    def fetch(event):
        try:
            center = client.get_fightcenter(str(event["id"]))
            return event, event_fights(event, center), []
        except EspnMmaNoFightCardError:
            return event, [], ["Event retained; the source has not published a usable card."]

    if all_events:
        process_cards(args, summary, client, PflImporter(supabase), all_events, events,
                      "espn_mma", ("pfl",), event_name, fetch, should_refresh, mark_refreshed)
    else:
        summary["provider_runs"]["espn_mma"].update(status="failed", events=0, fights=0,
                                                  requests=client.request_count, source="no_espn_listings")
    targets = missing(all_events)
    _, targets = include_followups(args, "pfl_official", targets, targets)
    if targets:
        summary["provider_runs"]["pfl_official"] = {"status": "running"}
        official = OfficialPflClient()
        try:
            verified = process_cards(args, summary, official, OfficialPflImporter(supabase),
                targets, targets, "pfl_official", ("pfl",), lambda entry: entry["name"],
                lambda entry: (*official.get_card(entry), []),
                lambda *unused: True, lambda *unused: None)
        except Exception as error:
            verified = []
            summary["provider_runs"]["pfl_official"].update(status="failed", message=safe_error(error))
            summary["warnings"].append({"stage": "pfl_official", "message": safe_error(error)})
        verified_ids = {entry["external_id"] for entry in verified}
        for entry in targets:
            if entry["external_id"] not in verified_ids:
                summary["catalog_issues"].append({"code": "DETAIL_SOURCE_GAP", "severity": "warning",
                    "event_id": entry.get("event_id"),
                    "promotion": "PFL", "event_name": entry["name"], "event_date": entry["date"],
                    "message": "The event is missing from ESPN and its official PFL card could not be verified; prior data was retained."})
        summary["provider_runs"]["espn_mma"]["official_fallback"] = dict(summary["provider_runs"]["pfl_official"])
        if not all_events and len(verified_ids) == len(targets) and catalog.get("status") == "completed":
            summary["provider_runs"]["espn_mma"].update(status="completed", source="official_pfl_fallback")
        elif not all_events and summary["provider_runs"]["pfl_official"].get("status") in {"completed", "partial"} and catalog.get("status") == "completed":
            summary["provider_runs"]["espn_mma"].update(status="completed_with_gaps", source="official_pfl_fallback")
    elif not all_events and catalog.get("status") == "completed":
        summary["provider_runs"]["espn_mma"].update(status="completed", source="verified_quiet_window")
    summary["providers"]["pfl"] = ("failed" if summary["provider_runs"]["espn_mma"]["status"] == "failed" else "automatic")
