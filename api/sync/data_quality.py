from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

try:
    from providers.manifest import is_active_promotion
except ModuleNotFoundError:  # Package-style unit tests run from the repository root.
    from api.providers.manifest import is_active_promotion


# Lines often first appear roughly five days out. Treat the exact five-day
# boundary as early, and begin flagging cards once they are four days away.
ODDS_EXPECTATION_DAYS = 4
HISTORY_LOOKAHEAD_DAYS = 21
INACTIVE_FIGHT_STATUSES = {"cancelled", "completed", "draw", "no_contest"}


def _fighter_name(fight: dict[str, Any], side: str) -> str:
    value = fight.get(side)
    if isinstance(value, dict):
        return str(value.get("full_name") or value.get("name") or "").strip()
    return ""


def _matchup(fight: dict[str, Any]) -> str:
    first = _fighter_name(fight, "fighter_a")
    second = _fighter_name(fight, "fighter_b")
    if first and second:
        return f"{first} vs {second}"
    return f"Fight #{fight.get('fight_id', 'unknown')}"


def _history_issue(
    code: str,
    severity: str,
    message: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "fighter_ids": [int(row["fighter_id"]) for row in rows],
    }


def audit_upcoming_coverage(
    supabase: Any,
    odds_days: int = ODDS_EXPECTATION_DAYS,
    history_days: int = HISTORY_LOOKAHEAD_DAYS,
) -> dict[str, Any]:
    """Audit upcoming-card completeness without treating distant odds as late."""

    today = datetime.now(ZoneInfo("America/Chicago")).date()
    end = today + timedelta(days=max(odds_days, history_days))
    events = (
        supabase.table("events")
        .select("event_id,event_name,event_date,promotion_id,card_observed_at,event_status,promotions(name)")
        .gte("event_date", today.isoformat())
        .lte("event_date", end.isoformat())
        .execute()
        .data
        or []
    )
    events = [
        row
        for row in events
        if is_active_promotion((row.get("promotions") or {}).get("name")) and row.get("event_status") not in {"cancelled","canceled"}
    ]
    event_by_id = {int(row["event_id"]): row for row in events}

    fights: list[dict[str, Any]] = []
    if event_by_id:
        fights = (
            supabase.table("fights")
            .select(
                "fight_id,event_id,fighter_a_id,fighter_b_id,fight_status,ruleset,"
                "fighter_a:fighters!fights_fighter_a_id_fkey(full_name),"
                "fighter_b:fighters!fights_fighter_b_id_fkey(full_name)"
            )
            .in_("event_id", list(event_by_id))
            .execute()
            .data
            or []
        )
    active = [
        row for row in fights if row.get("fight_status") not in INACTIVE_FIGHT_STATUSES
    ]

    fight_ids = [int(row["fight_id"]) for row in active]
    odds: list[dict[str, Any]] = []
    if fight_ids:
        odds = (
            supabase.table("mma_odds_observations")
            .select("observation_id,fight_id,fighter_id,sportsbook_key,observed_at,american_odds")
            .in_("fight_id", fight_ids)
            .execute()
            .data
            or []
        )
    cutoff = datetime.now(timezone.utc)-timedelta(hours=24)
    pairs = {}
    for row in odds:
        try:
            stamp=datetime.fromisoformat(str(row.get("observed_at") or "").replace("Z","+00:00"))
            price=int(row.get("american_odds") or 0)
            if not stamp.tzinfo or stamp<cutoff or stamp>datetime.now(timezone.utc)+timedelta(minutes=5) or -100<price<100: continue
            pairs.setdefault((int(row["fight_id"]),row["sportsbook_key"]),set()).add(int(row["fighter_id"]))
        except (ValueError,TypeError,KeyError): continue
    fights_with_odds = {int(f["fight_id"]) for f in active if any(
        {int(f["fighter_a_id"]),int(f["fighter_b_id"])}<=sides
        for (fight_id,_),sides in pairs.items() if fight_id==int(f["fight_id"]))}

    issues: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []
    for event_id, event in event_by_id.items():
        event_fights = [row for row in active if int(row["event_id"]) == event_id]
        promotion = (event.get("promotions") or {}).get("name") or "Unknown"
        event_date = date.fromisoformat(str(event["event_date"])[:10])
        days_until_event = (event_date - today).days
        odds_expected = days_until_event <= odds_days
        covered = sum(
            1 for row in event_fights if int(row["fight_id"]) in fights_with_odds
        )
        missing_fights = [
            row for row in event_fights if int(row["fight_id"]) not in fights_with_odds
        ]
        card = {
            "event_id": event_id,
            "event_name": event["event_name"],
            "event_date": event["event_date"],
            "promotion": promotion,
            "days_until_event": days_until_event,
            "fights": len(event_fights),
            "fights_with_odds": covered,
            "odds_expected": odds_expected,
            "missing_matchups": [
                {"fight_id": int(row["fight_id"]), "matchup": _matchup(row)}
                for row in missing_fights
            ],
        }
        cards.append(card)

        if days_until_event<=7:
            try:
                checked=datetime.fromisoformat(str(event.get("card_observed_at") or "").replace("Z","+00:00"))
                verified=checked.tzinfo and checked>=datetime.now(timezone.utc)-timedelta(hours=24)
            except ValueError:verified=False
            if not verified:issues.append({"code":"CARD_NOT_CHECKED","severity":"warning",**card,
                "message":"This upcoming event was not verified by a recent detailed card refresh."})

        if not event_fights:
            issues.append(
                {
                    "code": "CARD_EMPTY",
                    "severity": "warning",
                    **card,
                    "message": "Upcoming event has no active matchups.",
                }
            )
        elif odds_expected and covered == 0:
            issues.append(
                {
                    "code": "ODDS_CARD_EMPTY",
                    "severity": "warning",
                    **card,
                    "message": (
                        f"No tracked moneylines for {len(event_fights)} scheduled fights "
                        f"inside the {odds_days}-day odds window."
                    ),
                }
            )
        elif odds_expected and covered < len(event_fights):
            issues.append(
                {
                    "code": "ODDS_CARD_PARTIAL",
                    "severity": "warning",
                    **card,
                    "message": (
                        f"Moneylines cover {covered} of {len(event_fights)} scheduled "
                        f"fights inside the {odds_days}-day odds window."
                    ),
                }
            )

    duplicate_groups={}
    def canonical_name(value):
        import re,unicodedata
        return re.sub('[^a-z0-9]','',unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().casefold())
    for fight in active:
        names=tuple(sorted(canonical_name(_fighter_name(fight,side)) for side in ('fighter_a','fighter_b')))
        if not all(names):continue
        duplicate_groups.setdefault((fight['event_id'],names,fight.get('ruleset') or 'MMA'),[]).append(int(fight['fight_id']))
    for (event_id,_,_),ids in duplicate_groups.items():
        if len(ids)>1:issues.append({'code':'DUPLICATE_FIGHT','severity':'warning','event_id':event_id,'fight_ids':ids,
            'message':'Stored duplicate matchups need identity review; all saved bets were retained.'})

    fighter_ids = sorted(
        {
            int(row[key])
            for row in active
            for key in ("fighter_a_id", "fighter_b_id")
            if row.get(key)
        }
    )
    coverage: list[dict[str, Any]] = []
    if fighter_ids:
        coverage = (
            supabase.table("fighter_history_coverage")
            .select(
                "fighter_id,coverage_status,known_bout_count,next_event_id,coverage_note"
            )
            .in_("fighter_id", fighter_ids)
            .execute()
            .data
            or []
        )
    coverage_by_id = {int(row["fighter_id"]): row for row in coverage}
    missing_history = [
        {"fighter_id": fighter_id, "coverage_status": "unchecked"}
        for fighter_id in fighter_ids
        if fighter_id not in coverage_by_id
    ]
    pending = [row for row in coverage if row.get("coverage_status") == "pending"]
    partial = [
        row for row in coverage if row.get("coverage_status") == "partial_history"
    ]
    unavailable = [
        row
        for row in coverage
        if row.get("coverage_status")
        in {"regional_history_unavailable", "history_unavailable"}
    ]
    needs_review = [
        row for row in coverage if row.get("coverage_status") == "needs_review"
    ]
    confirmed_debuts = [
        row for row in coverage if row.get("coverage_status") == "confirmed_debut"
    ]

    unchecked = missing_history + pending
    if unchecked:
        issues.append(
            _history_issue(
                "HISTORY_UNCHECKED",
                "warning",
                f"{len(unchecked)} upcoming fighters are queued for automatic history review.",
                unchecked,
            )
        )
    if partial:
        issues.append(
            _history_issue(
                "HISTORY_PARTIAL",
                "info",
                f"{len(partial)} upcoming fighters have a partial public bout history.",
                partial,
            )
        )
    if unavailable:
        issues.append(
            _history_issue(
                "HISTORY_UNAVAILABLE",
                "info",
                (
                    f"{len(unavailable)} upcoming fighters were checked, but detailed "
                    "public history could not be recovered."
                ),
                unavailable,
            )
        )
    if needs_review:
        issues.append(
            _history_issue(
                "HISTORY_REVIEW",
                "warning",
                f"{len(needs_review)} fighter identity matches need review.",
                needs_review,
            )
        )

    unresolved = partial + unavailable + needs_review
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "gaps_found" if issues else "complete",
        "cards": cards,
        "issues": issues,
        "odds": {
            "expectation_window_days": odds_days,
            "covered_fights": sum(
                card["fights_with_odds"] for card in cards if card["odds_expected"]
            ),
            "expected_fights": sum(
                card["fights"] for card in cards if card["odds_expected"]
            ),
            "deferred_cards": sum(1 for card in cards if not card["odds_expected"]),
        },
        "history": {
            "fighters": len(fighter_ids),
            "checked": len(coverage),
            "unresolved": len(unresolved),
            "unchecked": len(unchecked),
            "partial": len(partial),
            "unavailable": len(unavailable),
            "needs_review": len(needs_review),
            "confirmed_debuts": len(confirmed_debuts),
        },
    }
