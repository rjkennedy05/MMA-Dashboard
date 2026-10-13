"""Bounded follow-up for missed results, using established source identities."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from providers.manifest import promotion_key
except ModuleNotFoundError:
    from api.providers.manifest import promotion_key


def resolved(fight):
    return (fight.get("fight_status") in {"cancelled", "draw", "no_contest"}
            or fight.get("result_type") in {"draw", "no_contest"}
            or fight.get("fight_status") == "completed" and fight.get("winner_id") is not None)


class ResultFollowupCache:
    def __init__(self, path, now=None):
        self.path = Path(path)
        self.now = now or datetime.now(timezone.utc)
        try:
            self.rows = json.loads(self.path.read_text())
            if not isinstance(self.rows, dict): self.rows = {}
        except (OSError, ValueError): self.rows = {}

    def due(self, eid):
        try:
            stamp = datetime.fromisoformat(self.rows[str(eid)]["next_attempt"])
            return not stamp.tzinfo or stamp <= self.now
        except (KeyError, TypeError, ValueError): return True

    def mark(self, eid, *, failed=False, source_complete=False):
        hours = .5 if failed else 72 if source_complete else 6
        self.rows[str(eid)] = {"checked_at": self.now.isoformat(),
            "next_attempt": (self.now+timedelta(hours=hours)).isoformat()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.rows, indent=2))
        temp.replace(self.path)


def select_followups(events, fights, mappings, sources, cache, *, past_days=2, limit=6):
    today = cache.now.astimezone(ZoneInfo("America/Chicago")).date()
    candidates = []
    for event in events:
        try: day = datetime.fromisoformat(str(event["event_date"])).date()
        except (KeyError, ValueError): continue
        if not today-timedelta(days=30) <= day < today-timedelta(days=past_days): continue
        key = promotion_key((event.get("promotions") or {}).get("name"))
        if key not in {"ufc", "dwcs", "pfl", "one", "bkfc", "lfa"}: continue
        rows = [f for f in fights if f["event_id"] == event["event_id"]]
        if event.get("event_status") in {"cancelled", "canceled"} or (rows and all(resolved(f) for f in rows)): continue
        if not cache.due(event["event_id"]): continue
        links = [m for m in mappings if m.get("entity_type") == "event" and m["internal_id"] == event["event_id"]]
        selected = None
        for link in links:
            name = str(sources.get(link["source_id"], "")).casefold()
            if key in {"ufc", "dwcs", "pfl"} and "espn" in name:
                selected = ("espn_mma" if key == "pfl" else "espn_ufc", {
                    "id": str(link["external_id"]), "name": event["event_name"],
                    "date": event.get("event_start_time") or event["event_date"]+"T12:00:00Z"})
                break
            if key == "one" and "one" in name:
                selected = ("one_championship", {"external_id": link["external_id"], "name": event["event_name"],
                    "date": datetime.fromisoformat(event.get("event_start_time") or event["event_date"]+"T12:00:00+00:00"),
                    "external_url": "https://www.onefc.com/events/"+link["external_id"]+"/", "status": event.get("event_status")})
                break
            if key == "bkfc" and "bkfc" in name:
                selected = ("bkfc", {"external_id": link["external_id"], "name": event["event_name"],
                    "date": datetime.fromisoformat(event.get("event_start_time") or event["event_date"]+"T12:00:00+00:00"),
                    "external_url": "https://www.bkfc.com/events/"+link["external_id"], "status": event.get("event_status")})
                break
            if key == "lfa" and "lfa" in name and link.get("external_url"):
                selected = ("lfa", {"external_id": link["external_id"], "name": event["event_name"],
                    "date": datetime.fromisoformat(event["event_date"]+"T12:00:00+00:00"),
                    "external_url": link["external_url"], "sherdog_url": link["external_url"],
                    "status": event.get("event_status")})
                break
            if key == "pfl" and "pfl" in name and "official" in name and link.get("external_url"):
                selected = ("pfl_official", {"external_id": link["external_id"], "name": event["event_name"],
                    "date": event["event_date"], "external_url": link["external_url"],
                    "promotion_key": "pfl", "event_id": event["event_id"]})
                break
        if selected:
            provider, seed = selected
            seed["_followup_event_id"] = event["event_id"]
            candidates.append((day, provider, seed))
    result = {}
    for _, provider, seed in sorted(candidates, key=lambda item:item[0], reverse=True)[:limit]:
        result.setdefault(provider, []).append(seed)
    return result


def load_followups(client, args, path):
    cache = ResultFollowupCache(path)
    today = cache.now.astimezone(ZoneInfo("America/Chicago")).date()
    events = client.table("events").select("event_id,event_name,event_date,event_start_time,event_status,promotions(name)").gte(
        "event_date", (today-timedelta(days=30)).isoformat()).lt("event_date", (today-timedelta(days=args.past_days)).isoformat()).execute().data or []
    ids = [e["event_id"] for e in events]
    if not ids: return cache, {}
    fights = client.table("fights").select("fight_id,event_id,fight_status,winner_id,result_type").in_("event_id", ids).execute().data or []
    maps = client.table("external_ids").select("entity_type,source_id,external_id,internal_id,external_url").eq(
        "entity_type", "event").in_("internal_id", ids).execute().data or []
    sources = {s["source_id"]:s["name"] for s in client.table("data_sources").select("source_id,name").execute().data or []}
    return cache, select_followups(events, fights, maps, sources, cache, past_days=args.past_days)


def include_followups(args, provider, all_events, events):
    queue = (getattr(args, "result_followups", {}) or {}).get(provider, [])
    def identity(row): return str(row.get("id") or row.get("external_id") or "")
    all_events, events = list(all_events), list(events)
    for seed in queue:
        known = next((e for e in all_events if identity(e) == identity(seed)), seed)
        tagged = {**known, "_followup_event_id": seed["_followup_event_id"]}
        if not any(identity(e) == identity(seed) for e in all_events): all_events.append(tagged)
        events = [e for e in events if identity(e) != identity(seed)] + [tagged]
    return all_events, events
