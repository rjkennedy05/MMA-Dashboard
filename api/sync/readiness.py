"""Publishable cards are distinct from process completion and optional gaps."""

import json

CARD_FLAGS = {
    "espn_ufc": "skip_ufc",
    "espn_mma": "skip_pfl",
    "one_championship": "skip_one",
    "lfa": "skip_lfa",
    "bkfc": "skip_bkfc",
}
COMPLETED = {"completed", "completed_with_gaps"}
CARD_DISPUTE_CODES = {"DETAIL_SOURCE_GAP", "CARD_EMPTY", "CARD_SOURCE_EMPTY",
                      "CARD_NOT_CHECKED", "CARD_SOURCE_OMISSION", "CARD_SOURCE_PLACEHOLDER",
                      "DUPLICATE_FIGHT"}


def card_disputes(summary):
    """Keep actionable card differences in the report instead of blocking posts."""
    disputes = {}
    for issue in [*(summary.get("catalog_issues") or []),
                  *((summary.get("quality_audit") or {}).get("issues") or [])]:
        if issue.get("code") not in CARD_DISPUTE_CODES:
            continue
        item = {key: issue[key] for key in ("code", "event_id", "event_name", "event_date", "fight_ids", "message")
                if key in issue}
        disputes[json.dumps(item, sort_keys=True)] = item
    for error in summary.get("errors") or []:
        if error.get("stage") not in {*CARD_FLAGS, "pfl_official"} or not error.get("context"):
            continue
        item = {"code": "CARD_IMPORT_REVIEW", "event_name": error["context"],
                "message": "The latest card update needs review; saved information was retained."}
        item.update({key: error[key] for key in ("event_id", "event_date", "fight_ids") if error.get(key) is not None})
        disputes[json.dumps(item, sort_keys=True)] = item
    return [disputes[key] for key in sorted(disputes)]


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
    reviewed_sources = {error.get("stage") for error in summary.get("errors") or [] if error.get("context")}
    failures = [
        key for key in expected if (runs.get(key) or {}).get("status") not in COMPLETED
        and not ((runs.get(key) or {}).get("status") == "partial" and key in reviewed_sources)
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
    disputes = card_disputes(summary)
    provider_promotions = {"espn_ufc": {"ufc", "dwcs"}, "espn_mma": {"pfl"},
                           "one_championship": {"one"}, "lfa": {"lfa"}, "bkfc": {"bkfc"}}
    unavailable = set().union(*(provider_promotions[key] for key in failures)) if failures else set()
    if catalog_required and not catalog_ok:
        unavailable.update({"ufc", "dwcs", "pfl"})
    for card in (summary.get("quality_audit") or {}).get("cards", []):
        promotion = str(card.get("promotion") or "").casefold()
        if any(key in promotion or (key == "dwcs" and "contender" in promotion) for key in unavailable):
            disputes.append({"code": "CARD_IMPORT_REVIEW", "event_id": card["event_id"],
                "event_name": card["event_name"], "event_date": card["event_date"],
                "message": "A source check was unavailable; saved card information was retained."})
    source_usable = bool(expected and len(failures) < len(expected))
    reasons = []
    if not full:
        reasons.append("This was not a full daily card refresh.")
    if not source_usable:
        reasons.append("No card provider completed a usable refresh.")
    if not coverage_ok:
        reasons.append("The final coverage audit did not complete.")
    summary["publishable"] = bool(
        full
        and source_usable
        and coverage_ok
        and not args.dry_run
    )
    summary["publication_readiness"] = {
        "schema_version": 3,
        "ready": summary["publishable"],
        "reasons": reasons,
        "disputes": disputes,
        "checked_event_ids": sorted({int(value) for value in summary.get("checked_event_ids", [])}),
        "warnings": (["Card differences are marked for review; saved data was retained."] if disputes else [])
            + (["Some card sources were unavailable; their saved information may be incomplete."] if failures else [])
            + (["Official event discovery needs review; retained listings may be incomplete."] if catalog_required and not catalog_ok else []),
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
        or disputes
        or (catalog_required and not catalog_ok)
        or not coverage_ok
    ):
        summary["status"] = "partial"
    else:
        summary["status"] = "success"
    return summary
