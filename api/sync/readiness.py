"""Publishable cards are distinct from process completion and optional gaps."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

CARD_FLAGS = {
    "espn_ufc": "skip_ufc",
    "espn_mma": "skip_pfl",
    "one_championship": "skip_one",
    "lfa": "skip_lfa",
    "bkfc": "skip_bkfc",
}
COMPLETED = {"completed", "completed_with_gaps"}


def resolve_scope(args):
    if args.requested_scope != "all":
        return args.requested_scope
    skipped = [bool(getattr(args, flag)) for flag in CARD_FLAGS.values()]
    if all(skipped) and not args.skip_odds:
        return "odds"
    return "custom" if any(skipped) else "all"


def finalize_readiness(summary, args):
    runs = summary.get("provider_runs") or {}
    expected = [key for key, flag in CARD_FLAGS.items() if not getattr(args, flag)]
    failures = [
        key for key in expected if (runs.get(key) or {}).get("status") not in COMPLETED
    ]
    catalog_required = not args.skip_catalog and args.requested_scope in {
        "all",
        "ufc",
        "dwcs",
        "pfl",
    }
    catalog_ok = (runs.get("official_catalog") or {}).get("status") == "completed"
    coverage_ok = (summary.get("quality_audit") or {}).get("status") in {
        "complete",
        "gaps_found",
    }
    full = (
        args.mode == "daily"
        and args.requested_scope == "all"
        and len(expected) == len(CARD_FLAGS)
        and not args.skip_catalog
    )
    today = datetime.now(ZoneInfo("America/Chicago")).date()
    critical = []
    for issue in (summary.get("quality_audit") or {}).get("issues", []):
        day = str(issue.get("event_date") or "")[:10]
        if (
            issue.get("code")
            in {
                "DETAIL_SOURCE_GAP",
                "CARD_EMPTY",
                "CARD_SOURCE_EMPTY",
                "CARD_NOT_CHECKED",
                "CARD_SOURCE_OMISSION",
                "CARD_SOURCE_PLACEHOLDER",
            }
            and day
            and (today - timedelta(days=7)).isoformat()
            <= day
            <= (today + timedelta(days=7)).isoformat()
        ):
            critical.append(issue)
    reasons = []
    if critical:
        reasons.append("Upcoming event cards still need source verification.")
    if not full:
        reasons.append("This was not a full daily card refresh.")
    if failures:
        reasons.append("Card providers need review: " + ", ".join(failures))
    if catalog_required and not catalog_ok:
        reasons.append("Official event discovery was not verified.")
    if not coverage_ok:
        reasons.append("The final coverage audit did not complete.")
    summary["publishable"] = bool(
        full
        and not failures
        and not critical
        and catalog_ok
        and coverage_ok
        and not args.dry_run
    )
    summary["publication_readiness"] = {
        "schema_version": 2,
        "ready": summary["publishable"],
        "reasons": reasons,
    }
    optional_problem = summary.get("odds_status") in {
        "failed",
        "completed_with_gaps",
    } or bool(summary.get("warnings"))
    gaps = (summary.get("quality_audit") or {}).get("status") == "gaps_found"
    if (expected and len(failures) == len(expected)) or (
        not expected and not args.skip_odds and summary.get("odds_status") == "failed"
    ):
        summary["status"] = "failed"
    elif (
        failures
        or summary.get("errors")
        or optional_problem
        or gaps
        or (catalog_required and not catalog_ok)
        or not coverage_ok
    ):
        summary["status"] = "partial"
    else:
        summary["status"] = "success"
    return summary
