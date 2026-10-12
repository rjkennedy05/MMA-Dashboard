"""Carry source review markers into posts without changing saved fight status."""

from copy import deepcopy
from datetime import date
import json
import re
import unicodedata

READINESS_SCHEMA = 3
LABELS = {
    "CARD_SOURCE_OMISSION": "Not on the latest source card; saved matchup kept for review.",
    "CARD_SOURCE_EMPTY": "The latest source did not confirm this card; saved matchups are shown.",
    "CARD_EMPTY": "The source has not confirmed the matchups yet.",
    "CARD_NOT_CHECKED": "This card needs a fresh source check.",
    "DETAIL_SOURCE_GAP": "Detailed card information needs source confirmation.",
    "CARD_SOURCE_PLACEHOLDER": "Some fighter details still need confirmation.",
    "DUPLICATE_FIGHT": "A saved duplicate matchup needs review.",
    "CARD_IMPORT_REVIEW": "The latest card update needs review; saved information is shown.",
}


def readiness_contract(summary):
    ready = summary.get("publication_readiness") or {}
    if (not isinstance(ready, dict) or ready.get("schema_version") != READINESS_SCHEMA
            or not isinstance(ready.get("disputes"), list)
            or not isinstance(ready.get("checked_event_ids"), list)):
        return None
    if any(not isinstance(item, dict) or item.get("code") not in LABELS for item in ready["disputes"]):
        return None
    return ready


def _name(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def matches_event(issue, event, fights):
    if issue.get("event_id") is not None:
        return str(issue["event_id"]) == str(event["event_id"])
    ids = {str(value) for value in issue.get("fight_ids", [])}
    if ids and ids.intersection(str(f["fight_id"]) for f in fights):
        return True
    if not issue.get("event_name") or _name(issue["event_name"]) != _name(event["event_name"]):
        return False
    if issue.get("code") == "CARD_IMPORT_REVIEW" and not issue.get("event_date"):
        return True
    # Older diagnostics used UTC day labels. Require the same title and a day
    # within one day; new diagnostics use the saved event ID and CT calendar.
    try:
        return abs((date.fromisoformat(str(issue["event_date"])[:10])
                    - date.fromisoformat(str(event["event_date"])[:10])).days) <= 1
    except (KeyError, ValueError):
        return False


def event_disputes(data, state, event, fights):
    current = [issue for issue in data.get("card_disputes", []) if matches_event(issue, event, fights)]
    previous = state.get("events", {}).get(str(event["event_id"]), {}).get("data_disputes", [])
    if str(event["event_id"]) not in {str(value) for value in data.get("checked_event_ids", [])}:
        current = [*previous, *current]  # An unchecked/cached card cannot clear an older dispute.
    unique = {json.dumps(item, sort_keys=True): item for item in current}
    return [deepcopy(unique[key]) for key in sorted(unique)]


def fight_disputes(fight, disputes):
    return [issue for issue in disputes if str(fight["fight_id"]) in
            {str(value) for value in issue.get("fight_ids", [])}]


def dispute_note(disputes):
    messages = list(dict.fromkeys(LABELS.get(issue.get("code"), "Saved card information needs review.")
                                 for issue in disputes))
    return "⚠️ **Data dispute**\n\\* " + "\n\\* ".join(messages) if messages else ""
