from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = PROJECT_ROOT / "api"
UFCSTATS_ROOT = API_ROOT / "ufcstats"
REPORTS_ROOT = Path(__file__).resolve().parent / "reports"
sys.path.insert(0, str(API_ROOT))
sys.path.insert(0, str(UFCSTATS_ROOT))

from providers.fighter_history.client import (  # noqa: E402
    FighterHistoryProviderError,
    SherdogHistoryClient,
)
from providers.fighter_history.normalizer import (  # noqa: E402
    coverage_without_history,
    find_profile_url,
    normalized_name,
    parse_profile_history,
    parse_profile_record,
    record_total,
    resolved_history_count,
)
from providers.api_sports_mma.client import (  # noqa: E402
    ApiSportsMmaClient,
    ApiSportsMmaError,
    resolve_api_sports_key,
)
from providers.api_sports_mma.normalizer import normalize_history  # noqa: E402
from providers.manifest import is_active_promotion  # noqa: E402
from sync.lease import SyncLease, ImportBusyError
from providers.persistence import save_rows
from providers.errors import safe_error
from zoneinfo import ZoneInfo
from uploader import supabase  # noqa: E402


PROBLEM_STATUSES = {
    "partial_history",
    "confirmed_debut",
    "regional_history_unavailable",
    "history_unavailable",
    "needs_review",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")


def run_periodic_provider_refresh(days: int) -> dict[str, Any]:
    command = [
        sys.executable,
        str(API_ROOT / "sync" / "weekly_sync.py"),
        "--mode",
        "maintenance",
        "--past-days",
        str(days),
        "--future-days",
        "90",
        "--skip-ufcstats",
        "--skip-catalog",
        "--skip-odds",
        "--skip-stats",
        "--skip-retention",
        "--no-dashboard-status",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )
    return {
        "status": "completed" if completed.returncode == 0 else "partial",
        "exit_code": completed.returncode,
        "window_days": days,
    }


def run_post_event_enrichment() -> dict[str, Any]:
    command = [
        sys.executable,
        str(API_ROOT / "sync" / "weekly_sync.py"),
        "--mode", "maintenance",
        "--past-days", "7",
        "--future-days", "0",
        "--skip-catalog",
        "--skip-pfl",
        "--skip-one",
        "--skip-lfa",
        "--skip-bkfc",
        "--skip-odds",
        "--skip-retention",
        "--no-dashboard-status",
        "--requested-scope", "ufc",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )
    return {
        "status": "completed" if completed.returncode == 0 else "partial",
        "exit_code": completed.returncode,
        "window_days": 7,
    }


class HistoryRepository:
    def __init__(self) -> None:
        self._bout_count_cache: dict[int, int] = {}
        self._fallback_count_cache: dict[int, int] = {}

    def upcoming_fighters(self, days: int, due_only: bool = False) -> list[dict[str, Any]]:
        today = datetime.now(ZoneInfo("America/Chicago")).date()
        end = today + timedelta(days=days)
        event_response = (
            supabase.table("events")
            .select("event_id,event_name,event_date,promotion_id,promotions(name)")
            .gte("event_date", today.isoformat())
            .lte("event_date", end.isoformat())
            .execute()
        )
        events = event_response.data or []
        events = [
            row
            for row in events
            if is_active_promotion((row.get("promotions") or {}).get("name"))
        ]
        if not events:
            return []
        events_by_id = {int(row["event_id"]): row for row in events}
        fight_response = (
            supabase.table("fights")
            .select("fight_id,event_id,fighter_a_id,fighter_b_id,fight_status")
            .in_("event_id", list(events_by_id))
            .execute()
        )
        fighter_event: dict[int, dict[str, Any]] = {}
        for fight in fight_response.data or []:
            if fight.get("fight_status") == "cancelled":
                continue
            event = events_by_id.get(int(fight["event_id"]))
            if not event:
                continue
            for key in ("fighter_a_id", "fighter_b_id"):
                fighter_id = fight.get(key)
                if fighter_id is None:
                    continue
                current = fighter_event.get(int(fighter_id))
                if current is None or str(event["event_date"]) < str(current["event_date"]):
                    fighter_event[int(fighter_id)] = event

        if not fighter_event:
            return []
        fighter_response = (
            supabase.table("fighters")
            .select("fighter_id,full_name,record_summary,date_of_birth")
            .in_("fighter_id", list(fighter_event))
            .execute()
        )
        rows = []
        for fighter in fighter_response.data or []:
            fighter_id = int(fighter["fighter_id"])
            event = fighter_event[fighter_id]
            promotion = event.get("promotions") or {}
            rows.append({
                **fighter,
                "event_id": int(event["event_id"]),
                "event_name": event.get("event_name"),
                "event_date": event.get("event_date"),
                "promotion_name": promotion.get("name"),
            })
        rows = sorted(rows, key=lambda row: (row.get("event_date") or "", row["full_name"]))
        if not due_only or not rows:
            return rows
        coverage = (
            supabase.table("fighter_history_coverage")
            .select("fighter_id,coverage_status,next_check_at")
            .in_("fighter_id", [row["fighter_id"] for row in rows])
            .execute().data or []
        )
        by_id = {int(row["fighter_id"]): row for row in coverage}
        now = datetime.now(timezone.utc)
        due = []
        for fighter in rows:
            stored = by_id.get(int(fighter["fighter_id"]))
            if not stored:
                due.append(fighter)
                continue
            next_check = stored.get("next_check_at")
            problem = stored.get("coverage_status") in PROBLEM_STATUSES | {"pending"}
            try:
                is_due = not next_check or datetime.fromisoformat(str(next_check).replace("Z", "+00:00")) <= now
            except ValueError:
                is_due = True
            if problem and is_due:
                due.append(fighter)
        return due

    def all_fighters_by_name(self) -> dict[str, list[dict[str, Any]]]:
        response = supabase.table("fighters").select(
            "fighter_id,full_name,record_summary,date_of_birth"
        ).execute()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in response.data or []:
            grouped.setdefault(normalized_name(row.get("full_name")), []).append(row)
        return grouped

    def official_bout_count(self, fighter_id: int) -> int:
        if fighter_id not in self._bout_count_cache:
            response = (
                supabase.table("fights")
                .select("fight_id,fight_status")
                .or_(f"fighter_a_id.eq.{fighter_id},fighter_b_id.eq.{fighter_id}")
                .in_("fight_status", ["completed", "draw", "no_contest"])
                .execute()
            )
            self._bout_count_cache[fighter_id] = len(response.data or [])
        return self._bout_count_cache[fighter_id]

    def fallback_bout_count(self, fighter_id: int) -> int:
        if fighter_id not in self._fallback_count_cache:
            response = (
                supabase.table("fighter_history_entries")
                .select("fighter_history_entry_id,source_id,fight_status,outcome")
                .eq("fighter_id", fighter_id)
                .execute()
            )
            counts: dict[int, int] = {}
            for row in response.data or []:
                if str(row.get("fight_status") or "").casefold() == "cancelled":
                    continue
                if str(row.get("outcome") or "").upper() == "CANCELLED":
                    continue
                source_id = int(row.get("source_id") or 0)
                counts[source_id] = counts.get(source_id, 0) + 1
            self._fallback_count_cache[fighter_id] = max(counts.values(), default=0)
        return self._fallback_count_cache[fighter_id]

    def history_source_id(self, name: str) -> int:
        response = (
            supabase.table("data_sources")
            .select("source_id")
            .eq("name", name)
            .limit(1)
            .execute()
        )
        if not response.data:
            raise RuntimeError(
                f"{name} source is missing. Run the included Supabase migrations."
            )
        return int(response.data[0]["source_id"])

    def save_fallback_history(
        self,
        fighter_id: int,
        source_id: int,
        history: list[dict[str, Any]],
    ) -> int:
        payloads=[]
        for entry in history:
            stored_entry = {
                key: value
                for key, value in entry.items()
                if key != "opponent_url"
            }
            payload = {
                "fighter_id": fighter_id,
                "source_id": source_id,
                **stored_entry,
                "updated_at": utc_now(),
            }
            payloads.append(payload)
        if payloads:
            save_rows(supabase,"fighter_history_entries",payloads)
        resolved_count = resolved_history_count(history)
        self._fallback_count_cache[fighter_id] = max(
            self._fallback_count_cache.get(fighter_id, 0), resolved_count
        )
        return resolved_count

    def save_coverage(
        self,
        fighter: dict[str, Any],
        status: str,
        known_bout_count: int,
        source_used: str,
        note: str,
        attempts: list[dict[str, str]],
        history_fighter_id: int | None = None,
    ) -> None:
        checked_at = datetime.now(timezone.utc)
        payload = {
            "fighter_id": int(fighter["fighter_id"]),
            "history_fighter_id": history_fighter_id,
            "next_event_id": fighter.get("event_id"),
            "next_event_name": fighter.get("event_name"),
            "next_event_date": fighter.get("event_date"),
            "promotion_name": fighter.get("promotion_name"),
            "coverage_status": status,
            "record_summary": fighter.get("record_summary"),
            "known_bout_count": known_bout_count,
            "source_used": source_used,
            "coverage_note": note,
            "attempts": attempts,
            "last_checked_at": checked_at.isoformat(),
            "next_check_at": (checked_at + timedelta(days=7)).isoformat(),
            "updated_at": checked_at.isoformat(),
        }
        save_rows(supabase,"fighter_history_coverage",[payload])


def compatible_duplicate(
    fighter: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    if int(fighter["fighter_id"]) == int(candidate["fighter_id"]):
        return False
    fighter_dob = fighter.get("date_of_birth")
    candidate_dob = candidate.get("date_of_birth")
    return not fighter_dob or not candidate_dob or fighter_dob == candidate_dob


def audit_fighter(
    repository: HistoryRepository,
    client: SherdogHistoryClient,
    sherdog_source_id: int,
    api_sports_client: ApiSportsMmaClient | None,
    api_sports_source_id: int | None,
    fighter: dict[str, Any],
    fighters_by_name: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    fighter_id = int(fighter["fighter_id"])
    attempts: list[dict[str, str]] = []
    official_count = repository.official_bout_count(fighter_id)
    expected_count = record_total(fighter.get("record_summary"))
    expected_label = f"/{expected_count}" if expected_count else ""
    attempts.append({"source": "connected archive", "result": f"{official_count}{expected_label} bouts"})
    if official_count and (expected_count is None or official_count >= expected_count):
        repository.save_coverage(
            fighter, "complete", official_count, "Connected provider archive",
            "Stored official/provider history is available.", attempts,
        )
        return {"status": "complete", "bouts": official_count}

    fallback_count = repository.fallback_bout_count(fighter_id)
    if fallback_count and (expected_count is None or fallback_count >= expected_count):
        attempts.append({"source": "stored fallback history", "result": f"{fallback_count}{expected_label} bouts"})
        repository.save_coverage(
            fighter, "fallback_history", fallback_count, "Stored fallback history",
            "Targeted fallback history is available.", attempts,
        )
        return {"status": "fallback_history", "bouts": fallback_count}
    if fallback_count:
        attempts.append({"source": "stored fallback history", "result": f"partial {fallback_count}{expected_label} bouts"})

    best_count = max(official_count, fallback_count)
    linked_history_id = None

    name_key = normalized_name(fighter.get("full_name"))
    linked_candidates = []
    for candidate in fighters_by_name.get(name_key, []):
        if not compatible_duplicate(fighter, candidate):
            continue
        count = repository.official_bout_count(int(candidate["fighter_id"]))
        if count:
            linked_candidates.append((candidate, count))
    if len(linked_candidates) == 1:
        candidate, count = linked_candidates[0]
        linked_history_id = int(candidate["fighter_id"])
        best_count = max(best_count, count)
        attempts.append({"source": "stored identity reconciliation", "result": f"linked {count}{expected_label} bouts"})
        if expected_count is None or count >= expected_count:
            repository.save_coverage(
                fighter, "linked_history", count, "Stored identity reconciliation",
                "History was found under one compatible stored fighter identity.", attempts,
                history_fighter_id=linked_history_id,
            )
            return {"status": "linked_history", "bouts": count}
    elif len(linked_candidates) > 1:
        attempts.append({"source": "stored identity reconciliation", "result": "multiple matches"})
        repository.save_coverage(
            fighter, "needs_review", 0, "Stored identity reconciliation",
            "Multiple stored fighter identities have this name; history was not attached automatically.", attempts,
        )
        return {"status": "needs_review", "bouts": 0}
    else:
        attempts.append({"source": "stored identity reconciliation", "result": "no match"})

    if api_sports_client and api_sports_source_id:
        try:
            api_fighter = api_sports_client.find_fighter(fighter["full_name"])
            history = normalize_history(
                api_sports_client.fighter_fights(api_fighter["id"]), api_fighter
            ) if api_fighter and api_fighter.get("id") is not None else []
            attempts.append({
                "source": "API-Sports MMA history",
                "result": (
                    f"{resolved_history_count(history)} resolved bouts"
                    if api_fighter else "no unambiguous fighter"
                ),
            })
            if history:
                count = repository.save_fallback_history(
                    fighter_id, api_sports_source_id, history
                )
                best_count = max(best_count, count)
                if expected_count is None or count >= expected_count:
                    repository.save_coverage(
                        fighter, "fallback_history", count, "API-Sports MMA",
                        "Bout history was recovered by the API-Sports fallback.", attempts,
                    )
                    return {"status": "fallback_history", "bouts": count}
        except ApiSportsMmaError as error:
            attempts.append({"source": "API-Sports MMA history", "result": f"unavailable: {safe_error(error)}"})
        except Exception as error:
            attempts.append({"source": "API-Sports MMA history", "result": f"error: {safe_error(error)}"})
    else:
        attempts.append({"source": "API-Sports MMA history", "result": "not configured"})

    try:
        search_html, search_url = client.search(fighter["full_name"])
        profile_url = find_profile_url(search_html, fighter["full_name"], search_url)
        if profile_url:
            profile_html, final_url = client.profile(profile_url)
            history = parse_profile_history(profile_html, final_url)
            for entry in history[:12]:
                opponent_url = entry.get("opponent_url")
                if not opponent_url:
                    continue
                try:
                    opponent_html, _ = client.profile(opponent_url)
                    entry["opponent_record"] = parse_profile_record(opponent_html)
                except FighterHistoryProviderError:
                    continue
        else:
            history = []
        attempts.append({
            "source": "Sherdog targeted history",
            "result": (
                f"{resolved_history_count(history)} resolved bouts"
                if profile_url else "no unambiguous profile"
            ),
        })
        if history:
            count = repository.save_fallback_history(fighter_id, sherdog_source_id, history)
            best_count = max(best_count, count)
            if expected_count is None or count >= expected_count:
                repository.save_coverage(
                    fighter, "fallback_history", count, "Sherdog Fighter History",
                    "Bout history was recovered by the final public fallback source.", attempts,
                )
                return {"status": "fallback_history", "bouts": count}
    except FighterHistoryProviderError as error:
        attempts.append({"source": "Sherdog targeted history", "result": f"unavailable: {safe_error(error)}"})
    except Exception as error:
        attempts.append({"source": "Sherdog targeted history", "result": f"error: {safe_error(error)}"})

    if best_count:
        status = "partial_history"
        note = (
            f"Recovered {best_count} of approximately {expected_count} professional bouts; "
            "remaining public bout details were not available."
            if expected_count else
            f"Recovered {best_count} public bouts, but completeness could not be verified."
        )
    else:
        status, note = coverage_without_history(fighter.get("record_summary"))
    repository.save_coverage(
        fighter, status, best_count, "All history sources checked", note, attempts,
        history_fighter_id=linked_history_id,
    )
    return {"status": status, "bouts": best_count}


def save_run(summary: dict[str, Any], run_id=None):
    record = {
        "started_at": summary["started_at"],
        "finished_at": summary["finished_at"],
        "status": summary["status"],
        "fighters_checked": summary["fighters_checked"],
        "histories_found": summary["histories_found"],
        "confirmed_debuts": summary["confirmed_debuts"],
        "unavailable_histories": summary["unavailable_histories"],
        "needs_review": summary["needs_review"],
        "summary": summary,
    }
    if run_id is not None: record["history_maintenance_run_id"]=run_id
    saved=save_rows(supabase,"history_maintenance_runs",[record])
    if not saved: raise RuntimeError("History run status was not saved.")
    return saved[0]["history_maintenance_run_id"]


def build_parser():
    configure_utf8_console()
    parser = argparse.ArgumentParser(description="Maintain history coverage for upcoming fighters.")
    parser.add_argument("--upcoming-days", type=int, default=21)
    parser.add_argument("--archive-days", type=int, default=365)
    parser.add_argument("--skip-provider-refresh", action="store_true")
    parser.add_argument("--due-only", action="store_true")
    parser.add_argument("--max-fighters", type=int, default=0)
    return parser


def execute_maintenance(args) -> int:
    summary: dict[str, Any] = {
        "started_at": utc_now(),
        "finished_at": None,
        "status": "running",
        "provider_refresh": {"status": "skipped"},
        "post_event_enrichment": {"status": "skipped"},
        "fighters_checked": 0,
        "histories_found": 0,
        "confirmed_debuts": 0,
        "unavailable_histories": 0,
        "needs_review": 0,
        "errors": [],
    }
    run_id=save_run(summary)
    print("=" * 64)
    print("MMA DASHBOARD WEEKLY HISTORY MAINTENANCE")
    print("=" * 64)

    if not args.skip_provider_refresh:
        summary["provider_refresh"] = run_periodic_provider_refresh(args.archive_days)
        summary["post_event_enrichment"] = run_post_event_enrichment()
        for stage in ("provider_refresh", "post_event_enrichment"):
            if summary[stage].get("exit_code"):
                summary["errors"].append({
                    "fighter": None,
                    "stage": stage,
                    "message": f"{stage.replace('_', ' ').title()} finished with provider issues.",
                })

    repository = HistoryRepository()
    client = SherdogHistoryClient()
    try:
        sherdog_source_id = repository.history_source_id("Sherdog Fighter History")
        api_sports_source_id = None
        api_sports_client = None
        api_sports_key, _api_sports_key_environment = resolve_api_sports_key()
        if api_sports_key:
            api_sports_source_id = repository.history_source_id("API-Sports MMA")
            api_sports_client = ApiSportsMmaClient(
                max_requests=max(2, (args.max_fighters or 12) * 2)
            )
        upcoming = repository.upcoming_fighters(args.upcoming_days, args.due_only)
        if args.max_fighters > 0:
            upcoming = upcoming[:args.max_fighters]
        fighters_by_name = repository.all_fighters_by_name()
        print(f"Upcoming fighters to audit: {len(upcoming)}")
        for index, fighter in enumerate(upcoming, start=1):
            print(f"[{index}/{len(upcoming)}] {fighter['full_name']}")
            try:
                result = audit_fighter(
                    repository, client, sherdog_source_id,
                    api_sports_client, api_sports_source_id,
                    fighter, fighters_by_name,
                )
                summary["fighters_checked"] += 1
                status = result["status"]
                if result["bouts"]:
                    summary["histories_found"] += 1
                if status == "confirmed_debut":
                    summary["confirmed_debuts"] += 1
                if status in {"partial_history", "regional_history_unavailable", "history_unavailable"}:
                    summary["unavailable_histories"] += 1
                if status == "needs_review":
                    summary["needs_review"] += 1
                print(f"  {status.replace('_', ' ').upper()} — {result['bouts']} bouts")
            except Exception as error:
                summary["needs_review"] += 1
                summary["errors"].append({
                    "fighter": fighter["full_name"],
                    "message": safe_error(error),
                    "context": safe_error(traceback.format_exc(limit=4)),
                })
                print(f"  HISTORY CHECK FAILED — {safe_error(error)}")
    except Exception as error:
        summary["errors"].append({
            "fighter": None,
            "message": safe_error(error),
            "context": safe_error(traceback.format_exc(limit=5)),
        })

    summary["finished_at"] = utc_now()
    if summary["errors"]:
        summary["status"] = "partial" if summary["fighters_checked"] else "failed"
    elif summary["needs_review"]:
        summary["status"] = "partial"
    else:
        summary["status"] = "success"

    save_run(summary,run_id)
    REPORTS_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = REPORTS_ROOT / f"history_{stamp}.json"
    report.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 64)
    print(f"Status:              {summary['status'].upper()}")
    print(f"Fighters checked:    {summary['fighters_checked']}")
    print(f"Histories available: {summary['histories_found']}")
    print(f"Confirmed debuts:    {summary['confirmed_debuts']}")
    print(f"Unavailable:         {summary['unavailable_histories']}")
    print(f"Needs review:        {summary['needs_review']}")
    print(f"Local report:        {report}")
    print("=" * 64)
    # Missing public history is a coverage finding, not a broken scheduled
    # task. Only technical errors should produce a failing process code.
    return 1 if summary["errors"] else 0


def main() -> int:
    args=build_parser().parse_args()
    try:
        with SyncLease(supabase):
            return execute_maintenance(args)
    except ImportBusyError as error:
        print(safe_error(error)); return 75
    except Exception as error:
        print("History maintenance stopped: "+safe_error(error)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
