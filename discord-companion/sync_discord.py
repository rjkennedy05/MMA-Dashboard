#!/usr/bin/env python3
"""Import app analysis and weekly cards; coordinate publisher metadata."""
from __future__ import annotations

import argparse
from copy import deepcopy
from contextlib import contextmanager
from datetime import date, datetime, time as daytime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from setup_discord import (APIError, DiscordAPI, NoRedirects, ROOT, SetupError,
                           overwrite_list, private_permissions, snowflake)
from provider_runtime import EXPECTED_ACTIVE_PROMOTIONS, ARCHIVED_PROMOTIONS
from bet_bridge import bet_payloads, fetch_bets
from state_store import load_state, save_state
from snapshot_merge import merge_external
from database_snapshot import SnapshotReader,publisher_lease
from card_disputes import readiness_contract, event_disputes, fight_disputes, dispute_note

ALIASES = {
    "ufc": "ufc", "ultimate fighting championship": "ufc",
    "dwcs": "dwcs", "dana whites contender series": "dwcs",
    "dana white contender series": "dwcs", "contender series": "dwcs",
    "lfa": "lfa", "legacy fighting alliance": "lfa",
    "pfl": "pfl", "professional fighters league": "pfl",
    "one": "one", "one championship": "one", "one fc": "one",
    "bkfc": "bkfc", "bare knuckle fighting championship": "bkfc",
    "rizin": "rizin", "rizin fighting federation": "rizin", "rizin ff": "rizin",
}
TABLE_IDS = {"events": "event_id", "fights": "fight_id", "odds": "odds_id",
             "event_research": "event_id", "external_ids": "external_id_map_id",
             "data_sync_runs": "data_sync_run_id", "fight_research": "fight_id",
             "bet_tickets": "ticket_id", "bet_legs": "leg_id"}
ACTIVE_PROMOTIONS = frozenset(EXPECTED_ACTIVE_PROMOTIONS)
RETIRED_PROMOTIONS = frozenset(ARCHIVED_PROMOTIONS)
EVENT_COLUMNS = "event_id,event_name,event_date,event_start_time,event_status,watch_platform,city,state_region,country,updated_at,card_observed_at,promotions(name)"
FIGHT_COLUMNS = ("fight_id,event_id,fighter_a_id,fighter_b_id,fight_order,fight_status,"
                 "source_observed_at,result_confirmed_at,ruleset,bout_type,winner_id,method,result_type,finish_round,finish_time_seconds,"
                 "fighter_a:fighters!fights_fighter_a_id_fkey(fighter_id,full_name),"
                 "fighter_b:fighters!fights_fighter_b_id_fkey(fighter_id,full_name),weight_classes(name)")
BIG_SWING = 0.05  # Five implied-probability percentage points since the last alert.


def chicago():
    try:
        return ZoneInfo("America/Chicago")
    except ZoneInfoNotFoundError:
        raise SetupError("Central Time data is missing. Run: python -m pip install -r requirements.txt") from None


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def promotion(event):
    row = event.get("promotions") or {}
    return ALIASES.get(normalized(row.get("name")), "")


def parsed_time(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except ValueError:
        return None


def local_day(event):
    instant = parsed_time(event.get("event_start_time"))
    if instant:
        return instant.astimezone(chicago()).date()
    try:
        return date.fromisoformat(str(event.get("event_date"))[:10])
    except ValueError:
        return None


def week_window(now):
    if not now.tzinfo:
        raise SetupError("An aware timestamp is required for the weekly rollover.")
    local = now.astimezone(chicago())
    monday = local.date() - timedelta(days=local.weekday())
    if local.weekday() == 0 and local.time().replace(tzinfo=None) < daytime(6):
        monday -= timedelta(days=7)
    return monday, monday + timedelta(days=7)


def ct_time(value):
    instant = parsed_time(value)
    if not instant:
        return "Time TBA"
    local = instant.astimezone(chicago())
    return local.strftime("%a %b %d, %I:%M %p").replace(" 0", " ") + " CT"


def status(value):
    value = normalized(value)
    if value in {"live", "in progress", "inprogress"}:
        return "live"
    if value in {"completed", "complete", "final", "draw", "no contest"}:
        return "completed"
    if value in {"cancelled", "canceled", "abandoned"}:
        return "cancelled"
    if value == "unknown":return "unknown"
    if value == "postponed":
        return "postponed"
    return "scheduled"


def final_bout(fight):
    if status(fight.get("fight_status"))=="cancelled":return True
    if normalized(fight.get("fight_status")) in {"draw","no contest"} or normalized(fight.get("result_type")) in {"draw","no contest"}:return True
    return status(fight.get("fight_status"))=="completed" and fight.get("winner_id") is not None


def read_env(path):
    result = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip().strip("\"'")
    return result


def local_config():
    saved = read_env(ROOT / ".env")
    keys = ("DISCORD_GUILD_ID", "DISCORD_BOT_TOKEN", "MMA_DASHBOARD_PATH")
    config = {key: saved.get(key) or os.environ.get(key, "") for key in keys}
    if not all(config.values()):
        raise SetupError("Run 04-CONNECT-DASHBOARD.bat first to save the local connection settings.")
    config["DISCORD_GUILD_ID"] = snowflake(config["DISCORD_GUILD_ID"], "Server ID")
    return config


class DatabaseReader:
    """Restricted snapshots and publisher coordination; keys stay in local env files."""
    def __init__(self, dashboard):
        path = Path(dashboard).expanduser().resolve() / "api" / ".env"
        if not path.is_file():
            raise SetupError("The selected dashboard folder must contain api/.env from your working dashboard.")
        config = read_env(path)
        self.bet_owner_id = (read_env(ROOT / ".env").get("MMA_DASHBOARD_BET_OWNER_ID")
                             or os.environ.get("MMA_DASHBOARD_BET_OWNER_ID"))
        self.url = config.get("SUPABASE_URL", "").rstrip("/")
        self.key = (read_env(ROOT / ".env").get("MMA_DISCORD_SUPABASE_KEY")
                    or os.environ.get("MMA_DISCORD_SUPABASE_KEY") or config.get("SUPABASE_SECRET_KEY") or config.get("SUPABASE_SERVICE_KEY")
                    or config.get("SUPABASE_SERVICE_ROLE_KEY") or "")
        parsed = urlparse(self.url)
        if (parsed.scheme != "https" or not re.fullmatch(r"[a-z0-9-]+\.supabase\.co", parsed.hostname or "")
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path or parsed.port):
            raise SetupError("SUPABASE_URL must be your HTTPS project URL ending in .supabase.co.")
        if not self.key:
            raise SetupError("The working dashboard's api/.env is missing its server-side Supabase credential.")
        self.opener = build_opener(NoRedirects())

    def rows(self, table, params):
        if table not in TABLE_IDS:
            raise SetupError("This bridge only reads approved dashboard sync and event-data tables.")
        collected = []
        seen_pages = set()
        for _ in range(200):
            query = list(params) + [("order", TABLE_IDS[table] + ".asc"),
                                   ("limit", "500"), ("offset", str(len(collected)))]
            headers = {"apikey": self.key, "Accept": "application/json", "User-Agent": "MMA-Discord-Bridge/2.0"}
            if not self.key.startswith("sb_secret_"):
                headers["Authorization"] = "Bearer " + self.key
            request = Request(self.url + "/rest/v1/" + table + "?" + urlencode(query), headers=headers, method="GET")
            try:
                with self.opener.open(request, timeout=30) as response:
                    page = json.loads(response.read())
            except HTTPError as error:
                raise SetupError(f"Database read failed for {table} (HTTP {error.code}). Check the working api/.env and table permissions.") from None
            except (URLError, TimeoutError, OSError):
                raise SetupError(f"Database read did not finish for {table}; no partial table will be published.") from None
            if not isinstance(page, list):
                raise SetupError(f"Unexpected database response for {table}.")
            if not page:
                return collected
            digest = fingerprint(page)
            if digest in seen_pages:
                raise SetupError(f"Database pagination did not advance for {table}.")
            seen_pages.add(digest)
            collected.extend(page)
        raise SetupError(f"Database read exceeded the page limit for {table}; stopped before publishing incomplete data.")

    def control_rpc(self,name,arguments):
        if name not in {"mma_discord_snapshot","mma_discord_publisher"}:
            raise SetupError("This bridge only accepts a snapshot read or publisher coordination.")
        headers={"apikey":self.key,"Content-Type":"application/json","Accept":"application/json"}
        if not self.key.startswith("sb_secret_"):headers["Authorization"]="Bearer "+self.key
        request=Request(self.url+"/rest/v1/rpc/"+name,data=json.dumps(arguments).encode(),headers=headers,method="POST")
        try:
            with self.opener.open(request,timeout=30) as response: return json.loads(response.read())
        except (HTTPError,URLError,TimeoutError,OSError):
            raise SetupError("Dashboard snapshot/coordination was unavailable. Existing Discord information was kept; verify migrations 032–035 and retry after the import finishes.") from None

    def latest_daily_sync(self, now):
        """Return today's newest full daily refresh, ignoring scoped/manual maintenance."""
        if not now.tzinfo:
            raise SetupError("An aware timestamp is required for the dashboard sync handshake.")
        local = now.astimezone(chicago())
        start = datetime.combine(local.date(), daytime.min, chicago()).astimezone(timezone.utc)
        rows = self.rows("data_sync_runs", [
            ("select", "data_sync_run_id,started_at,finished_at,status,summary"),
            ("started_at", "gte." + start.isoformat()),
        ])
        daily = []
        for row in rows:
            summary = row.get("summary") or {}
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except ValueError:
                    summary = {}
            if summary.get("run_mode") == "daily" and summary.get("requested_scope", "all") == "all":
                daily.append(row)
        return max(daily, key=lambda row: int(row["data_sync_run_id"])) if daily else None

    def wait_for_daily_sync(self, now, timeout_seconds=4500, poll_seconds=30, sleeper=time.sleep):
        """Do not publish Discord's morning snapshot before the dashboard has finished."""
        deadline = time.monotonic() + timeout_seconds
        while True:
            row = self.latest_daily_sync(now)
            state = normalized((row or {}).get("status"))
            summary=(row or {}).get("summary") or {}
            if isinstance(summary,str):
                try: summary=json.loads(summary)
                except ValueError: summary={}
            ready=readiness_contract(summary)
            if state in {"success", "partial"} and row.get("finished_at") and summary.get("publishable") is True and ready and ready.get("ready") is True:
                return row
            if state in {"success", "partial"}:
                raise SetupError("Today's refresh is not ready for this bot. Run a full daily refresh with the matching dashboard and Discord releases; card disputes will then be shown on the posts.")
            if state == "failed":
                raise SetupError("Today's dashboard refresh failed. Discord kept its previous snapshot and will retry in one hour.")
            if time.monotonic() >= deadline:
                if row:
                    raise SetupError("Today's dashboard refresh is still running. Discord kept its previous snapshot and will retry in one hour.")
                raise SetupError("No full dashboard refresh started today. Discord kept its previous snapshot and will retry in one hour.")
            sleeper(min(poll_seconds, max(0, deadline - time.monotonic())))


def batches(values, size=80):
    return [values[i:i + size] for i in range(0, len(values), size)]


def fetch_data(reader, now, previous, *, require_ready=True):
    start, end = week_window(now)
    review = {}
    if isinstance(reader,DatabaseReader):
        daily = reader.latest_daily_sync(now)
        summary = (daily or {}).get("summary") or {}
        if isinstance(summary, str):
            summary = json.loads(summary)
        review = readiness_contract(summary) or {}
        if require_ready and (not daily or not daily.get("finished_at")
                or daily.get("status") not in {"success", "partial"}
                or summary.get("publishable") is not True or review.get("ready") is not True):
            raise SetupError("The latest full dashboard refresh is not ready. Finish a matching daily refresh before publishing.")
        pending=[int(eid) for eid,item in previous.get("events",{}).items() if not item.get("archived")]
        tables=reader.control_rpc("mma_discord_snapshot",{"p_start":(start-timedelta(days=2)).isoformat(),
            "p_end":(end+timedelta(days=2)).isoformat(),"p_pending":pending})
        after = reader.latest_daily_sync(now)
        if fingerprint(daily) != fingerprint(after):
            raise SetupError("Dashboard data changed while reading the card. Retry after the refresh finishes.")
        if not review and daily:
            raise SetupError("Install the matching dashboard and bot updates, then run a full daily refresh.")
        reader=SnapshotReader(tables,reader.bet_owner_id)
    events = reader.rows("events", [("select", EVENT_COLUMNS),
        ("event_date", "gte." + (start - timedelta(days=2)).isoformat()),
        ("event_date", "lt." + (end + timedelta(days=2)).isoformat())])
    pending_ids = [str(eid) for eid, item in previous.get("events", {}).items() if not item.get("archived")]
    for batch in batches(pending_ids):
        events.extend(reader.rows("events", [("select", EVENT_COLUMNS), ("event_id", "in.(" + ",".join(batch) + ")")]))
    events = list({str(e["event_id"]): e for e in events}.values())
    eligible = [e for e in events if promotion(e) in ACTIVE_PROMOTIONS and not re.fullmatch(r"(?:ufc )?(?:import )?test event(?: [0-9]+)?", normalized(e["event_name"]))
                and normalized(e["event_name"]) not in {"ufc test event", "ufc import test"}]
    research_ids = [str(e["event_id"]) for e in eligible
                    if local_day(e) and start <= local_day(e) < end]
    wanted_ids = [str(e["event_id"]) for e in eligible if
                  (local_day(e) and start <= local_day(e) < end) or str(e["event_id"]) in pending_ids]
    fights = []
    for batch in batches(wanted_ids):
        fights.extend(reader.rows("fights", [("select", FIGHT_COLUMNS), ("event_id", "in.(" + ",".join(batch) + ")")]))
    result = {"events": eligible, "fights": fights, "odds": [], "research": [], "links": [], "warnings": [],
              "card_disputes": review.get("disputes", []), "checked_event_ids": review.get("checked_event_ids", [])}
    optional = [
        ("odds", [str(f["fight_id"]) for f in fights], "fight_id", "odds_id,fight_id,fighter_id,sportsbook,sportsbook_key,american_odds,recorded_at"),
        ("external_ids", wanted_ids, "internal_id", "internal_id,external_url"),
        ("event_research", research_ids, "event_id", "event_id,assistant_card_analysis"),
    ]
    for table, ids, column, columns in optional:
        key = {"event_research": "research", "external_ids": "links"}.get(table, table)
        try:
            rows = []
            for batch in batches(ids):
                query = [("select", columns), (column, "in.(" + ",".join(batch) + ")")]
                if table == "odds":
                    query.append(("market_type", "eq.moneyline"))
                if table == "external_ids":
                    query.append(("entity_type", "eq.event"))
                if table == "event_research":
                    query.append(("assistant_card_analysis", "not.is.null"))
                rows.extend(reader.rows(table, query))
            result[key] = rows
        except SetupError:
            result[key] = None
            result["warnings"].append(f"{key} unavailable; existing Discord information will be preserved.")
    try:
        result["bets"], result["bet_owner_id"] = fetch_bets(
            reader, research_ids, getattr(reader, "bet_owner_id", None) or previous.get("bet_owner_id"))
    except SetupError as error:
        result["bets"] = None
        result["warnings"].append("Saved bets unavailable; existing My Bets was preserved. " + str(error))
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def split_text(text, limit=1750):
    """Conservative UTF-16 limits; prefer line/word boundaries."""
    pieces = []
    while text:
        units, boundary = 0, 0
        for index, char in enumerate(text):
            count = 2 if ord(char) > 0xFFFF else 1
            if units + count > limit:
                break
            units += count
            boundary = index + 1
        if boundary == len(text):
            pieces.append(text)
            break
        preferred = max(text.rfind("\n", 0, boundary), text.rfind(" ", 0, boundary))
        cut = preferred + 1 if preferred > boundary // 2 else boundary
        pieces.append(text[:cut])
        text = text[cut:]
    return pieces or ["No information available yet."]


def units(text):
    return len(str(text).encode("utf-16-le")) // 2


def clipped(text, limit):
    value = str(text or "").strip()
    return split_text(value, limit)[0].strip() if value else "TBA"


def embed_pages(title, description, fields, *, footer="Times shown in Central Time", per_page=8):
    """One embed per message, within the field and combined text limits."""
    base = {"title": clipped(title, 256), "description": clipped(description, 1200),
            "color": 0xDDA344, "footer": {"text": clipped(footer, 200)}}
    pages, current = [], []
    size = sum(units(base[k]) for k in ("title", "description")) + units(base["footer"]["text"])
    for field in fields:
        field = {"name": clipped(field["name"], 256), "value": clipped(field["value"], 1024),
                 "inline": bool(field.get("inline", False))}
        extra = units(field["name"]) + units(field["value"])
        if current and (len(current) >= per_page or size + extra > 5500):
            pages.append(dict(base, fields=current, footer=dict(base["footer"])))
            current, size = [], sum(units(base[k]) for k in ("title", "description")) + units(base["footer"]["text"])
        current.append(field)
        size += extra
    pages.append(dict(base, footer=dict(base["footer"]), **({"fields": current} if current else {})))
    for index, page in enumerate(pages):
        if len(pages) > 1:
            page["footer"]["text"] = clipped(footer, 170) + f" • {index + 1}/{len(pages)}"
    return [{"content": "", "embeds": [page]} for page in pages]


def strip_research_imports(value):
    """Keep the write-up; remove the dashboard's v4 import contract and payloads."""
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").strip()
    if "MMA DASHBOARD CARD RESPONSE CONTRACT" in text and "CARD DATA" in text:
        return ""
    try:
        if isinstance(json.loads(text), (dict, list)):
            return ""
    except (ValueError, TypeError):
        pass
    text = re.sub(r"```(?:json)?\s*\n(.*?)```",
                  lambda m: "" if re.search(r'"(?:dashboard_import_key|fighter_a_style|assistant_pick|fights)"\s*:', m[1]) else m[0],
                  text, flags=re.S | re.I)
    kept = []
    in_import, import_level = False, 0
    for line in text.splitlines():
        heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*$", line)
        label = (heading[2] if heading else line).strip().strip("*").strip()
        if ((heading and re.match(r"^Dashboard\s+(?:Import|Export|Data|Facts)\b", label, re.I))
                or re.fullmatch(r"Dashboard\s+(?:Import|Export|Data|Facts)\s*:?", label, re.I)):
            in_import, import_level = True, len(heading[1]) if heading else 2
            continue
        if in_import:
            if heading and len(heading[1]) <= import_level:
                in_import = False
            else:
                continue
        if re.match(r"^\s*(?:[-*]\s+)?\*{0,2}(?:Dashboard\s+facts?|Decision\s+data)\b", line, re.I):
            continue
        if re.match(r"^\s*(?:\*\*)?A\s+style\s*=", line, re.I) and "B style=" in line:
            continue
        line = re.sub(r"\s*\[\s*(?:key|fight[_\s-]*id|dashboard_import_key)\s*=\s*[^\]]+\]", "", line, flags=re.I)
        line = re.sub(r"(?:cite|genui).*?", "", line)
        kept.append(line.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def readable_tables(text):
    """Turn markdown comparison tables into labeled fighter snapshots."""
    lines, output, index = text.splitlines(), [], 0
    def cells(line):
        return [cell.strip() for cell in line.strip().strip("|").split("|")]
    def separator(line):
        values = cells(line)
        return len(values) >= 2 and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in values)
    while index < len(lines):
        if index + 1 < len(lines) and "|" in lines[index] and separator(lines[index + 1]):
            headers, rows = cells(lines[index]), []
            index += 2
            while index < len(lines) and "|" in lines[index] and len(cells(lines[index])) == len(headers):
                rows.append(cells(lines[index]))
                index += 1
            if len(headers) >= 3 and not headers[0]:
                for column in range(1, len(headers)):
                    output.append("**" + headers[column].strip("*") + "**")
                    output.extend("• **" + row[0].strip("*") + ":** " + row[column] for row in rows)
                    output.append("")
            else:
                for row in rows:
                    output.append("**" + row[0].strip("*") + "**")
                    output.extend("• **" + (headers[column] or "Detail").strip("*") + ":** " + row[column]
                                  for column in range(1, len(headers)))
                    output.append("")
        else:
            output.append(lines[index])
            index += 1
    return "\n".join(output).strip()


def research_payloads(event, analysis):
    text = strip_research_imports(analysis)
    if not text:
        return []
    # Split at fight/card-summary boundaries, keeping every narrative section.
    chunks, title, body = [], "Card research", []
    def finish():
        if body:
            cleaned = readable_tables("\n".join(body)).strip()
            cleaned = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*$", r"\n\n**\1**\n\n", cleaned)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            if cleaned:
                pieces = split_text(cleaned, 3500)
                for part, piece in enumerate(pieces):
                    suffix = f" • continued {part + 1}/{len(pieces)}" if len(pieces) > 1 else ""
                    chunks.append({"content": "", "embeds": [{"title": "🧠 " + clipped(title, 216) + suffix,
                                   "description": piece.strip(), "color": 0xDDA344,
                                   "author": {"name": clipped(event["event_name"], 256)},
                                   "footer": {"text": "Full card research"}}]})
    for line in text.splitlines():
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line) or re.match(r"^\s*\*\*(.+?)\*\*\s*$", line)
        candidate = heading[1].strip().strip("*").strip() if heading else ""
        if heading and (re.match(r"^(?:Fight\s+\d+\s*[:.\-–—]|Card\s+Summary\b)", candidate, re.I)
                        or (re.search(r"\s(?:vs\.?|versus)\s", candidate, re.I) and not candidate.endswith(":"))):
            finish()
            title, body = candidate, []
        else:
            body.append(line)
    finish()
    return chunks


def safe_url(value):
    try:
        parsed = urlparse(str(value or ""))
        if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
            return str(value)
    except ValueError:
        pass
    return None


def odds_text(value):
    try:
        number = int(value)
        return f"{number:+d}" if abs(number) >= 100 else "TBA"
    except (ValueError, TypeError):
        return "TBA"


def probability(value):
    number = float(value)
    return -number / (100 - number) if number < 0 else 100 / (100 + number)


def odds_history(rows):
    history = {}
    valid = [r for r in rows or [] if odds_text(r.get("american_odds")) != "TBA"
             and parsed_time(r.get("recorded_at"))]
    for row in sorted(valid, key=lambda r: (parsed_time(r["recorded_at"]), int(r.get("odds_id") or 0))):
        if odds_text(row.get("american_odds")) == "TBA" or not parsed_time(row.get("recorded_at")):
            continue
        book = row.get("sportsbook_key") or normalized(row.get("sportsbook"))
        if not book:
            continue
        key = f"{row['fight_id']}:{row['fighter_id']}:{book}"
        pair = history.setdefault(key, {"first": row, "latest": row})
        pair["latest"] = row
    return history


def pair_prices(fight, history):
    a, b = str(fight.get("fighter_a_id")), str(fight.get("fighter_b_id"))
    prefix = str(fight["fight_id"]) + ":"
    sides = {a: {}, b: {}}
    for key, pair in history.items():
        if key.startswith(prefix):
            _, side, book = key.split(":", 2)
            if side in sides:
                sides[side][book] = pair
    common = set(sides[a]) & set(sides[b])
    candidates = common or (set(sides[a]) | set(sides[b]))
    if not candidates:
        return None, None
    def freshness(book):
        times = [parsed_time(side[book]["latest"]["recorded_at"]) for side in sides.values() if book in side]
        return min(times), book
    book = max(candidates, key=freshness)
    return sides[a].get(book), sides[b].get(book)


def matchup(fight):
    return ((fight.get("fighter_a") or {}).get("full_name") or "Fighter TBA") + " vs " + ((fight.get("fighter_b") or {}).get("full_name") or "Fighter TBA")


def result_text(fight):
    if status(fight.get("fight_status")) != "completed":
        return ""
    winner = next((side.get("full_name") for side in (fight.get("fighter_a") or {}, fight.get("fighter_b") or {})
                   if side.get("fighter_id") is not None and str(side["fighter_id"]) == str(fight.get("winner_id"))), None)
    result_kind = normalized(fight.get("result_type") or fight.get("fight_status"))
    label = {"draw": "Draw", "no contest": "No contest"}.get(result_kind)
    result = label or ("Winner: " + winner if winner else "Result awaiting confirmation")
    details = [str(v) for v in (fight.get("method"), "Rd " + str(fight["finish_round"]) if fight.get("finish_round") else None) if v]
    return result + (" • " + " • ".join(details) if details else "")


def event_slug(event):
    base = re.sub(r"[^a-z0-9]+", "-", normalized(event["event_name"]))[:70].strip("-")
    return (base or promotion(event)) + "-" + (local_day(event).isoformat() if local_day(event) else "date-tba")


def event_topic(event):
    return f"{event['event_name'][:180]} | Card, results, odds and My Bets | Card reference {event['event_id']}"


def header_payload(event, links, override, disputes=()):
    day = local_day(event)
    location = ", ".join(str(event[k]) for k in ("city", "state_region", "country") if event.get(k)) or "Location TBA"
    fields = [
        {"name": "Date", "value": day.strftime("%A, %B %d").replace(" 0", " ") if day else "Date TBA", "inline": True},
        {"name": "Start", "value": ct_time(event.get("event_start_time")), "inline": True},
        {"name": "Watch", "value": override.get("watch_platform") or event.get("watch_platform") or "Broadcast TBA"},
        {"name": "Location", "value": location},
    ]
    source_links = []
    for url in (links or []) + (override.get("links") or []):
        if safe_url(url) and url not in source_links:
            source_links.append(url)
    if source_links:
        def link_label(url):
            host = (urlparse(url).hostname or "Source").removeprefix("www.")
            return {"tapology.com": "Tapology", "espn.com": "ESPN", "ufc.com": "UFC", "onefc.com": "ONE"}.get(host, host)
        fields.append({"name": "Event links", "value": "\n".join(f"[{link_label(url)}](<{url}>)" for url in source_links[:5] if len(url) < 175)})
    description = f"**{promotion(event).upper()}** • {status(event.get('event_status')).title()}"
    if disputes:
        description += "\n\n" + dispute_note(disputes)
    payload = embed_pages("🗓️ " + event["event_name"] + (" *" if disputes else ""), description, fields,
                          footer="Updated " + ct_time(event.get("updated_at")))[0]
    poster = safe_url(override.get("poster_url"))
    if poster:
        payload["embeds"][0]["image"] = {"url": poster}
    return payload


def card_payloads(fights, history=None, disputes=()):
    fields = []
    for index, fight in enumerate(sorted(fights, key=lambda f: (f.get("fight_order") is None, f.get("fight_order") or 0, int(f["fight_id"]))), 1):
        names = ((fight.get("fighter_a") or {}).get("full_name") or "Fighter TBA", (fight.get("fighter_b") or {}).get("full_name") or "Fighter TBA")
        marker = " • CANCELLED" if status(fight.get("fight_status")) == "cancelled" else ""
        review = fight_disputes(fight, disputes)
        if review:
            marker += " *"
        block = f"{names[0]} vs {names[1]}"
        if review:
            block += "\n" + dispute_note(review)
        if result_text(fight):
            block += "\n✅ **" + result_text(fight) + "**"
        fields.append({"name": f"Fight {index}{marker}", "value": block})
    if not fights:
        fields.append({"name": "Card pending", "value": "The fight card is awaiting confirmation."})
    pages = embed_pages("🥊 Fight card" + (" *" if disputes else ""), dispute_note(disputes), fields, footer="MMA FightCenter", per_page=25)
    embeds = [embed for page in pages for embed in page["embeds"]]
    for embed in embeds:
        embed["footer"]["text"] = "MMA FightCenter"
    size = sum(units(embed.get("title", "")) + units(embed.get("description", ""))
               + units(embed["footer"]["text"])
               + sum(units(field["name"]) + units(field["value"]) for field in embed.get("fields", []))
               for embed in embeds)
    if len(embeds) > 10 or size > 5400:
        raise SetupError("The fight card exceeds Discord's single-message limit. The existing card was kept.")
    return [{"content": "", "embeds": embeds}]


def snapshot(event, fights, history, disputes=()):
    return {"event_status": status(event.get("event_status")), "day": str(local_day(event)),
            "data_disputes": deepcopy(list(disputes)),
            "fights": {str(f["fight_id"]): {"matchup": matchup(f), "status": status(f.get("fight_status")),
                                         "result": result_text(f), "order": f.get("fight_order")} for f in fights},
            "prices": {key: {"price": pair["latest"]["american_odds"], "at": pair["latest"]["recorded_at"],
                              "book": pair["latest"].get("sportsbook") or "Book TBA"}
                       for key, pair in history.items() if key.split(":", 1)[0] in {str(f["fight_id"]) for f in fights}}}


def eligible_price_sides(fights):
    return {f"{f['fight_id']}:{f[side]}" for f in fights
            if status(f.get("fight_status")) in {"scheduled", "live"}
            for side in ("fighter_a_id", "fighter_b_id") if f.get(side) is not None}


def price_swings(anchors, prices, fights):
    eligible, swings = eligible_price_sides(fights), []
    for key, item in prices.items():
        parts = key.split(":", 2)
        if ":".join(parts[:2]) not in eligible or len(parts) < 3 or not parts[2]:
            continue
        prior = anchors.get(key)
        if prior and odds_text(prior.get("price")) != "TBA" and odds_text(item.get("price")) != "TBA":
            delta = probability(item["price"]) - probability(prior["price"])
            if abs(delta) + 1e-12 >= BIG_SWING:
                swings.append((key, prior, item, delta))
    return swings


def next_price_anchors(anchors, prices, fights):
    eligible = eligible_price_sides(fights)
    updated = {key: value for key, value in anchors.items() if ":".join(key.split(":", 2)[:2]) in eligible}
    alerted = {key for key, *_ in price_swings(anchors, prices, fights)}
    for key, item in prices.items():
        if ":".join(key.split(":", 2)[:2]) in eligible and (key not in updated or key in alerted):
            updated[key] = dict(item)
    return updated


def changes(before, after, fights, price_anchors=None):
    if not before:
        return []
    notes = []
    if before.get("data_disputes", []) != after.get("data_disputes", []):
        notes.append("Data dispute: saved card information needs review; affected matchups are marked *."
                     if after.get("data_disputes") else "Data dispute cleared: the latest source check resolved the card differences.")
    if before.get("day") != after["day"]:
        notes.append(f"Event date changed: {before.get('day')} → {after['day']}.")
    if before.get("event_status") != after["event_status"]:
        notes.append("Event status: " + after["event_status"].title() + ".")
    old, new = before.get("fights", {}), after["fights"]
    for fid, item in new.items():
        if fid not in old:
            notes.append("Added to card: " + item["matchup"] + ".")
        else:
            if old[fid]["matchup"] != item["matchup"]:
                notes.append("Matchup changed: " + old[fid]["matchup"] + " → " + item["matchup"] + ".")
            if old[fid]["status"] != item["status"] and item["status"] == "cancelled":
                notes.append("Cancelled on the source card: " + item["matchup"] + ".")
            if item["result"] and old[fid].get("result") != item["result"]:
                notes.append(item["matchup"] + " — " + item["result"] + ".")
    for fid, item in old.items():
        if fid not in new:
            notes.append("Not listed on the latest source card: " + item["matchup"] + ".")
    # Older saved snapshots have no order field. Establish it quietly on their
    # first refresh, then report confirmed changes to the running order.
    if any("order" in old[fid] and old[fid]["order"] != item.get("order")
           for fid, item in new.items() if fid in old):
        notes.append("Fight order updated.")
    fighter_names = {str(side.get("fighter_id")): side.get("full_name", "Fighter") for f in fights for side in (f.get("fighter_a") or {}, f.get("fighter_b") or {})}
    anchors = price_anchors if price_anchors is not None else before.get("prices", {})
    for key, prior, item, delta in price_swings(anchors, after["prices"], fights):
        name = fighter_names.get(key.split(":", 2)[1], "Fighter")
        notes.append(f"Line movement — **{name}**, {item['book']}: **{odds_text(prior['price'])} → {odds_text(item['price'])}** "
                     f"({delta * 100:+.1f} percentage points; tracked {ct_time(item['at'])}).")
    return notes


def change_payloads(notes, now, revised_card=None):
    groups = {}
    for note in notes:
        title = ("⚠️ Data review" if note.startswith("Data dispute") else
                 "📈 Big odds swing" if note.startswith("Line movement") else
                 "✅ Results" if re.search(r" — (?:Winner:|Draw\b|No contest\b|Result awaiting)", note) else
                 "🔄 Card changes" if note.startswith(("Event date", "Event status", "Added", "Cancelled", "Matchup changed", "Absent", "Not listed", "Fight order")) else
                 "📰 News")
        groups.setdefault(title, []).append(note)
    payloads, card_posted = [], False
    for title, items in groups.items():
        if revised_card and title in {"🔄 Card changes", "✅ Results"}:
            if not card_posted:
                updated = deepcopy(revised_card)
                for payload in updated:
                    for embed in payload["embeds"]:
                        embed["title"] = embed["title"].replace("🥊 Fight card", "🔄 Updated fight card", 1)
                first = updated[0]["embeds"][0]
                if first.get("footer", {}).get("text") == "MMA FightCenter":
                    first["footer"]["text"] = "Updated " + now.astimezone(chicago()).strftime("%a %I:%M %p CT")
                payloads.extend(updated)
                card_posted = True
            continue
        for piece in split_text("\n\n".join("• " + item for item in items), 3500):
            payloads.append({"content": "", "embeds": [{"title": title, "description": piece.strip(),
                             "color": 0x57A88C if title.startswith("✅") else 0xDDA344,
                             "footer": {"text": now.astimezone(chicago()).strftime("%a %I:%M %p CT")}}]})
    return payloads


def payload_matches(message, payload):
    """Ignore Discord's extra embed metadata while comparing requested fields."""
    def includes(actual, expected):
        if isinstance(expected, dict):
            return isinstance(actual, dict) and all(includes(actual.get(k, False) if k == "inline" else actual.get(k), v)
                                                    for k, v in expected.items())
        if isinstance(expected, list):
            return isinstance(actual, list) and len(actual) == len(expected) and all(includes(a, e) for a, e in zip(actual, expected))
        return actual == expected
    return (message.get("content", "") == payload.get("content", "")
            and includes(message.get("embeds", []), payload.get("embeds", [])))


class Publisher:
    def __init__(self, api, setup, state_path):
        self.api, self.setup, self.path = api, setup, state_path
        self.state = load_state(state_path,{"guild_id": setup["guild_id"], "events": {}, "posts": {}})
        if self.state["guild_id"] != setup["guild_id"]:
            raise SetupError("The Discord sync state belongs to a different server.")
        self.bot = str(api.request("GET", "/users/@me")["id"])
        if self.bot != str(setup["bot_id"]):
            raise SetupError("Use the token for the bot that created this server's structure.")
        self.channels = api.request("GET", f"/guilds/{setup['guild_id']}/channels")
        self.recent = {}
        self.state.setdefault("archive_categories", [setup["channels"]["archive"]])
        for key in ("promotions", "upcoming", "archive"):
            channel = self.channel(setup["channels"][key])
            if channel["type"] != 4 or not private_permissions(channel, setup["guild_id"], self.bot):
                raise SetupError("A workspace category no longer has the expected private permissions.")
        for key in (*sorted(ACTIVE_PROMOTIONS), "this-week", "archive-index"):
            channel = self.channel(setup["channels"][key])
            parent_key = "upcoming" if key == "this-week" else "archive" if key == "archive-index" else "promotions"
            if (channel["type"] != 0 or channel.get("parent_id") != setup["channels"][parent_key]
                    or not private_permissions(channel, setup["guild_id"], self.bot)):
                raise SetupError("A saved promotion or index channel no longer has the expected private settings.")

    def mutate(self,method,route,payload=None):
        getattr(self,"ensure_publisher",lambda:None)()
        return self.api.request(method,route,payload)

    def channel(self, channel_id):
        found = next((c for c in self.channels if c["id"] == channel_id), None)
        if not found:
            raise SetupError("A saved workspace channel is missing. Restore the channel or rerun structure setup.")
        return found

    def save(self):
        save_state(self.path,self.state)

    def recent_messages(self, channel_id):
        if channel_id not in self.recent:
            messages=[]; before=None
            for _ in range(20):
                route=f"/channels/{channel_id}/messages?limit=100"+(f"&before={before}" if before else "")
                page=self.api.request("GET",route)
                if not page:break
                messages.extend(page);before=page[-1]["id"]
                if len(page)<100:break
            self.recent[channel_id]=messages
        return self.recent[channel_id]

    def post(self, key, channel_id, payload, *, pinned=False, seed=None, preserve=False):
        getattr(self,"ensure_publisher",lambda:None)()
        saved = self.state["posts"].get(key)
        digest = fingerprint(payload)
        message_id = saved["id"] if saved else seed
        message = None
        if message_id:
            try:
                message = self.api.request("GET", f"/channels/{channel_id}/messages/{message_id}")
            except APIError as error:
                if error.status != 404:
                    raise
        if message and str(message["author"]["id"]) != self.bot:
            raise SetupError("A saved message is not owned by this bot; it will not be changed.")
        if message and preserve and saved:
            if pinned and not message.get("pinned"):
                self.mutate("PUT", f"/channels/{channel_id}/messages/pins/{message['id']}")
            return message["id"]
        pending=self.state.setdefault("pending_posts",{}).get(key)
        if not message and pending:
            message=next((m for m in self.recent_messages(channel_id) if str(m["author"]["id"])==self.bot and payload_matches(m,pending["payload"])),None)
        if not message:
            message = next((m for m in self.recent_messages(channel_id) if str(m["author"]["id"]) == self.bot
                            and payload_matches(m, payload)), None)
        body = dict(payload, allowed_mentions={"parse": []})
        if message:
            if not payload_matches(message, payload):
                message = self.mutate("PATCH", f"/channels/{channel_id}/messages/{message['id']}", body)
        else:
            intent=(pending or {}).get("payload") or payload
            self.state["pending_posts"][key]={"channel_id":channel_id,"payload":intent}
            self.save()
            outgoing=dict(intent,allowed_mentions={"parse":[]},nonce=fingerprint([self.setup["guild_id"],key])[:24],enforce_nonce=True)
            message=self.mutate("POST",f"/channels/{channel_id}/messages",outgoing)
            if not payload_matches(message,payload):message=self.mutate("PATCH",f"/channels/{channel_id}/messages/{message['id']}",body)
            self.recent_messages(channel_id).insert(0, message)
        self.state["pending_posts"].pop(key,None)
        self.state["posts"][key] = {"id": message["id"], "hash": digest, "channel_id": channel_id}
        self.save()
        if pinned and not message.get("pinned"):
            self.mutate("PUT", f"/channels/{channel_id}/messages/pins/{message['id']}")
        return message["id"]

    def remove_display_post(self, key):
        getattr(self,"ensure_publisher",lambda:None)()
        """Remove a redundant generated display chunk after keeping a local copy."""
        if not re.fullmatch(r"(?:research:[0-9]+:(?:[a-f0-9]{20}|current)|event:[0-9]+:(?:card|bets)|weekly-index|archive-index):[0-9]+", key):
            raise SetupError("Cleanup is limited to generated card, bet, research and index chunks.")
        saved = self.state["posts"][key]
        try:
            message = self.api.request("GET", f"/channels/{saved['channel_id']}/messages/{saved['id']}")
        except APIError as error:
            if error.status != 404:
                raise
            message = None
        if message:
            if str(message["author"]["id"]) != self.bot:
                raise SetupError("A redundant message is not owned by this bot; cleanup stopped.")
            self.state.setdefault("display_backups", {}).setdefault(saved["id"], {
                "channel_id": saved["channel_id"], "content": message.get("content", ""),
                "embeds": message.get("embeds", []), "pinned": message.get("pinned", False)})
            self.save()
            self.mutate("DELETE", f"/channels/{saved['channel_id']}/messages/{saved['id']}")
            if saved["channel_id"] in self.recent:
                self.recent[saved["channel_id"]][:] = [m for m in self.recent[saved["channel_id"]] if m["id"] != saved["id"]]
        del self.state["posts"][key]
        self.save()

    def block(self, key, channel_id, payloads, *, pin_first=False, seed=None, prune=False):
        for index, payload in enumerate(payloads):
            self.post(f"{key}:{index}", channel_id, payload, pinned=pin_first and index == 0, seed=seed if index == 0 else None)
        surplus = []
        for candidate in self.state["posts"]:
            match = re.fullmatch(re.escape(key) + r":([0-9]+)", candidate)
            if match and int(match[1]) >= len(payloads):
                surplus.append((int(match[1]), candidate))
        for _, candidate in sorted(surplus):
            if prune:
                self.remove_display_post(candidate)
            else:
                self.post(candidate, channel_id, {"content": "This section was updated. See its current first message.", "embeds": []})

    def event_channel(self, event):
        getattr(self,"ensure_publisher",lambda:None)()
        eid = str(event["event_id"])
        saved = self.state["events"].get(eid)
        channel = self.channel(saved["channel_id"]) if saved else None
        if not channel:
            matches = [c for c in self.channels if c["type"] == 0
                       and (c.get("topic") or "").endswith(" | Card reference " + eid)]
            if len(matches) > 1:
                raise SetupError("Multiple channels match this event; resolve the duplicate before syncing.")
            channel = matches[0] if matches else None
        if not channel:
            channel = self.mutate("POST", f"/guilds/{self.setup['guild_id']}/channels", {
                "name": event_slug(event), "type": 0, "topic": event_topic(event),
                "parent_id": self.setup["channels"]["upcoming"],
                "permission_overwrites": overwrite_list(self.setup["guild_id"], self.bot)})
            self.channels.append(channel)
            print("Created event channel: #" + channel["name"])
        if not private_permissions(channel, self.setup["guild_id"], self.bot):
            raise SetupError("An event channel has unexpected permissions; it will not be changed.")
        self.state["events"].setdefault(eid, {})["channel_id"] = channel["id"]
        self.save()
        return channel

    def move(self, channel, destination):
        getattr(self,"ensure_publisher",lambda:None)()
        if channel.get("parent_id") != destination:
            self.mutate("PATCH", f"/channels/{channel['id']}", {"parent_id": destination})
            channel["parent_id"] = destination

    def archive_destination(self):
        for category_id in self.state["archive_categories"]:
            category = self.channel(category_id)
            if not private_permissions(category, self.setup["guild_id"], self.bot):
                raise SetupError("An archive category has unexpected permissions.")
            if sum(c.get("parent_id") == category_id for c in self.channels) < 49:
                return category_id
        category = self.mutate("POST", f"/guilds/{self.setup['guild_id']}/channels", {
            "name": "🗄️ ARCHIVED EVENTS " + str(len(self.state["archive_categories"]) + 1), "type": 4,
            "permission_overwrites": overwrite_list(self.setup["guild_id"], self.bot)})
        self.channels.append(category)
        self.state["archive_categories"].append(category["id"])
        self.save()
        return category["id"]


def publish_research(publisher, event, analysis, channel_id=None, key=None):
    key = key or "research:" + str(event["event_id"]) + ":current"
    sources = publisher.state.setdefault("research_sources", {})
    previous=sources.get(key)
    if previous and previous.get("analysis")!=analysis:
        publisher.state.setdefault("research_revisions",{}).setdefault(str(event["event_id"]),{})[fingerprint(previous["analysis"])]=previous
    sources[key] = {"event": event, "analysis": analysis}
    publisher.save()  # Preserve the source before changing any existing chunks.
    channel_id = channel_id or publisher.setup["channels"][promotion(event)]
    publisher.block(key, channel_id, research_payloads(event, analysis), prune=True)
    if key.endswith(":current"):
        prefix="research:"+str(event["event_id"])+":"
        current_ids={saved["id"] for post,saved in publisher.state["posts"].items() if post.startswith(key+":")}
        for old in list(publisher.state["posts"]):
            if old.startswith(prefix) and not old.startswith(key+":"):
                if publisher.state["posts"][old]["id"] in current_ids:del publisher.state["posts"][old]
                else:publisher.remove_display_post(old)
    publisher.state.setdefault("research_display", {})[key] = 3
    publisher.save()


def migrate_research_display(publisher, event_ids):
    """Reformat this week's recorded research without replaying old cards."""
    groups = {}
    for key, saved in list(publisher.state["posts"].items()):
        match = re.fullmatch(r"(research:([0-9]+):[a-f0-9]{20}):([0-9]+)", key)
        if match and match[2] in event_ids and publisher.state.get("research_display", {}).get(match[1]) != 3:
            groups.setdefault(match[1], []).append((int(match[3]), saved, match[2]))
    for key, parts in groups.items():
        source = publisher.state.get("research_sources", {}).get(key)
        parts.sort(key=lambda part: part[0])
        channel_id = parts[0][1]["channel_id"]
        if channel_id not in {publisher.setup["channels"][p] for p in ACTIVE_PROMOTIONS}:
            raise SetupError("A recorded research post is outside the promotion channels; formatting stopped.")
        if not source:
            text, fallback_name = [], "Card research"
            for _, saved, _ in parts:
                try:
                    message = publisher.api.request("GET", f"/channels/{channel_id}/messages/{saved['id']}")
                except APIError as error:
                    if error.status == 404:
                        continue
                    raise
                if str(message["author"]["id"]) != publisher.bot:
                    raise SetupError("A recorded research message is not owned by this bot; formatting stopped.")
                content = message.get("content", "")
                header = re.match(r"^\*\*(.*?) — FULL CARD RESEARCH \([0-9]+/[0-9]+\)\*\*\n\n", content, re.S)
                if header:
                    fallback_name, content = header[1], content[header.end():]
                text.append(content)
            event = publisher.state["events"].get(parts[0][2], {}).get("event") or {
                "event_id": int(parts[0][2]), "event_name": fallback_name}
            source = {"event": event, "analysis": "".join(text)}
        publish_research(publisher, source["event"], source["analysis"], channel_id, key)
        print("Updated existing research formatting: " + source["event"]["event_name"])


def apply_external_data(data, state):
    return merge_external(data,state)


def publish_bets(publisher, eid, channel_id, records):
    item = publisher.state["events"][eid]
    key = "event:" + eid + ":bets"
    if records is None:
        records = item.get("bet_snapshot")
    if records is None:
        # Preserve an existing guide or an interrupted publication until a
        # complete dashboard read can replace it. New channels get a placeholder.
        if key in publisher.state["posts"] or any(
                re.fullmatch(re.escape(key) + r":[0-9]+", candidate) for candidate in publisher.state["posts"]):
            return
        publisher.post(key, channel_id, {"content": "", "embeds": [{"title": "🎟️ My Bets", "color": 0x57A88C,
            "description": "Saved FightCenter bets will appear here with the next successful research sync.\n"
                           "Your own notes and pinned messages stay available."}]}, pinned=True)
        return
    legacy = publisher.state["posts"].get(key)
    publisher.block(key, channel_id, bet_payloads(records), pin_first=True,
                    seed=legacy["id"] if legacy else None, prune=True)
    publisher.state["posts"].pop(key, None)
    item["bet_snapshot"] = deepcopy(records)
    publisher.save()


def publish_event(publisher, event, fights, now, history=None, links=None, override=None, *,
                  alert_prices=True, reset_prices=False, bets=None, disputes=None):
    eid = str(event["event_id"])
    channel = publisher.event_channel(event)
    item = publisher.state["events"][eid]
    disputes = item.get("data_disputes", []) if disputes is None else disputes
    links = links if links is not None else item.get("source_links", [])
    history = history if history is not None else item.get("odds_history", {})
    publisher.post("event:" + eid + ":header", channel["id"], header_payload(event, links, override or {}, disputes), pinned=True)
    payloads = card_payloads(fights, history, disputes)
    if item.get("external_card"):
        source = item["external_card"]
        for payload in payloads:
            payload["embeds"][0]["footer"]["text"] = clipped(source["source"] + " • Checked " + ct_time(source["checked_at"]), 200)
    publisher.block("event:" + eid + ":card", channel["id"], payloads, pin_first=True, prune=True)
    publish_bets(publisher, eid, channel["id"], bets)
    publisher.post("event:" + eid + ":news-guide", channel["id"], {"content": "", "embeds": [{"title": "🔄 Refresh this event", "color": 0xDDA344,
                   "description": "🥊 **/refreshfight** · Fetch this card and its published results.\n📈 **/refreshodds** · Fetch fresh prices and flag big swings.\n\n"
                                  "Big swings use a five-percentage-point change in implied probability."}]})
    after = snapshot(event, fights, history, disputes)
    anchors = {} if reset_prices else item.get("price_anchors", (item.get("snapshot") or {}).get("prices", {}))
    notes = changes(item.get("snapshot"), after, fights, anchors if alert_prices else after["prices"])
    if notes:
        def stable(value):
            if not value:
                return value
            result = deepcopy(value)
            for price in result.get("prices", {}).values():
                price.pop("at", None)
            return result
        key = "event:" + eid + ":news:" + fingerprint([stable(item.get("snapshot")), stable(after)])[:20]
        publisher.block(key, channel["id"], change_payloads(notes, now, revised_card=payloads))
    item.update(event=event, fights=deepcopy(fights), snapshot=after, odds_history=history,
                data_disputes=deepcopy(list(disputes)),
                source_links=links, price_anchors=next_price_anchors(anchors, after["prices"], fights))
    publisher.save()
    return notes


def publish_cycle(publisher, data, now, overrides=None):
    app_data = data
    data = apply_external_data(data, publisher.state)
    if data.get("bets") is not None and data.get("bet_owner_id"):
        # Bind before any Discord write so an interrupted first publication
        # cannot silently choose a different dashboard user on its retry.
        publisher.state["bet_owner_id"] = data["bet_owner_id"]
        publisher.save()
    start, end = week_window(now)
    events = {str(e["event_id"]): e for e in data["events"]}
    # Retired promotions remain readable, but can never return to this week's
    # active workspace or trigger a provider request.
    for eid, item in publisher.state["events"].items():
        saved_event = item.get("event") or item.get("seed_event") or {}
        if promotion(saved_event) in RETIRED_PROMOTIONS and not item.get("archived"):
            channel = publisher.channel(item["channel_id"])
            publisher.move(channel, publisher.archive_destination())
            item.update(archived=True, retired=True, event=saved_event)
            publisher.save()
            print("Retired to archive: " + (saved_event.get("event_name") or "RIZIN card"))
    active = sorted([e for e in events.values() if promotion(e) in ACTIVE_PROMOTIONS and local_day(e) and start <= local_day(e) < end],
                    key=lambda e: (local_day(e), e.get("event_start_time") or "", str(e["event_id"])))
    active_ids = {str(e["event_id"]) for e in active}
    history = odds_history(data.get("odds"))
    research = {str(r["event_id"]): r.get("assistant_card_analysis") or "" for r in data.get("research") or []}
    migrate_research_display(publisher, active_ids)
    for key in sorted(ACTIVE_PROMOTIONS):
        publisher.post("promotion-guide:" + key, publisher.setup["channels"][key], {
            "content": "", "embeds": [{"title": "🧠 " + key.upper() + " research", "color": 0xDDA344,
            "description": "This week's full card breakdowns and discussion.\n\n**🧠 Analysis** · Matchups, paths to victory and price assessments.\n"
                           "**🥊 Event channels** · Fight card, updates and My Bets."}]},
            pinned=True, seed=publisher.setup["messages"].get(key))
    for eid, analysis in research.items():
        event = events.get(eid)
        if eid in active_ids and event and analysis.strip():
            publish_research(publisher, event, analysis)
    pending = [events[eid] for eid, item in publisher.state["events"].items()
               if eid in events and eid not in active_ids and not item.get("archived")]
    for event in active + pending:
        eid = str(event["event_id"])
        raw_fights = [f for f in app_data["fights"] if str(f["event_id"]) == eid]
        raw_links = ([r for r in app_data.get("links") or [] if str(r["internal_id"]) == eid]
                     if app_data.get("links") is not None else None)
        channel = publisher.event_channel(event)
        if eid in active_ids:
            publisher.move(channel, publisher.setup["channels"]["upcoming"])
        item = publisher.state["events"][eid]
        item["seed_event"] = next((e for e in app_data["events"] if str(e["event_id"]) == eid), event)
        item["seed_fights"] = raw_fights
        if raw_links is not None:
            item["source_records"] = raw_links
        fights = [f for f in data["fights"] if str(f["event_id"]) == eid]
        links = ([r["external_url"] for r in data.get("links") or [] if str(r["internal_id"]) == eid and r.get("external_url")]
                 if data.get("links") is not None else None)
        fight_ids = {str(f["fight_id"]) for f in fights}
        event_history = ({key: value for key, value in history.items() if key.split(":", 1)[0] in fight_ids}
                         if data.get("odds") is not None else None)
        publish_event(publisher, event, fights, now, event_history, links, (overrides or {}).get(eid, {}),
                      alert_prices=False, bets=(data.get("bets") or {}).get(eid) if eid in active_ids else None,
                      disputes=event_disputes(data, publisher.state, event, fights))
        item.update(archived=False, week_start=start.isoformat())
        publisher.save()
    # Only dated past cards are moved. Missing source rows and live events are retained.
    for eid, item in publisher.state["events"].items():
        if item.get("archived") or eid not in events:
            continue
        event = events[eid]
        day = local_day(event)
        event_fights=[f for f in data["fights"] if str(f["event_id"])==eid]
        resolved=bool(event_fights) and all(final_bout(f) for f in event_fights)
        if day and day < start and resolved and status(event.get("event_status")) in {"completed", "cancelled"}:
            channel = publisher.channel(item["channel_id"])
            publisher.move(channel, publisher.archive_destination())
            item.update(archived=True, event=event)
            publisher.save()
            print("Archived: " + event["event_name"])
    index = []
    for event in active:
        item = publisher.state["events"][str(event["event_id"])]
        override = (overrides or {}).get(str(event["event_id"]), {})
        index.append({"name": "🥊 " + event["event_name"] + (" *" if item.get("data_disputes") else ""), "value":
                      f"🕒 {ct_time(event.get('event_start_time'))}\n📺 {override.get('watch_platform') or event.get('watch_platform') or 'Broadcast TBA'}\n"
                      f"{status(event.get('event_status')).title()} • Open card: <#{item['channel_id']}>"
                      + ("\n⚠️ Data dispute — see marked matchups." if item.get("data_disputes") else "")})
    if not active:
        index.append({"name": "No cards listed", "value": "No events from the tracked promotions are currently imported for this week."})
    retained = [(eid, item) for eid, item in publisher.state["events"].items()
                if not item.get("archived") and eid not in active_ids]
    if retained:
        for eid, item in retained:
            label = item.get("event", {}).get("event_name") or "Card reference " + eid
            index.append({"name": "📌 Preserved • " + label + (" *" if item.get("data_disputes") else ""),
                          "value": f"Live, rescheduled or awaiting source confirmation.\nOpen card: <#{item['channel_id']}>"
                          + ("\n⚠️ Data dispute — awaiting review." if item.get("data_disputes") else "")})
    publisher.block("weekly-index", publisher.setup["channels"]["this-week"],
                    embed_pages("📅 This week", f"{start.strftime('%b %d').replace(' 0', ' ')} – {(end - timedelta(days=1)).strftime('%b %d').replace(' 0', ' ')} • Central Time", index),
                    pin_first=True, seed=publisher.setup["messages"].get("this-week"), prune=True)
    archived = sorted([item for item in publisher.state["events"].values() if item.get("archived")],
                      key=lambda item: item["event"].get("event_date") or "", reverse=True)
    archive_fields = [{"name": item["event"]["event_name"], "value": f"{local_day(item['event']) or 'Date TBA'} • <#{item['channel_id']}>"} for item in archived]
    if not archive_fields:
        archive_fields = [{"name": "Archive ready", "value": "Past event channels will appear here after the weekly rollover."}]
    publisher.block("archive-index", publisher.setup["channels"]["archive-index"],
                    embed_pages("🗄️ Past cards", "Event details, results and bets remain available.", archive_fields),
                    pin_first=True, seed=publisher.setup["messages"].get("archive-index"), prune=True)
    publisher.state["last_success"] = now.isoformat()
    publisher.save()
    print(f"Synced {len(active)} weekly events; {len(archived)} event channels archived.")
    for warning in data.get("warnings", []):
        print("Note: " + warning)


@contextmanager
def sync_lock():
    with (ROOT / "sync.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SetupError("The Discord updater is already running. Close that updater before starting another.") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="Run the command bot with a daily app check.")
    mode.add_argument("--preview", action="store_true", help="Read the database and show this week's cards; make no Discord changes.")
    args = parser.parse_args()
    if args.watch:
        from run_bot import main as command_main
        command_main()
        return
    config = local_config()
    from provider_runtime import configure_provider_core
    configure_provider_core(config["MMA_DASHBOARD_PATH"])
    setup_path = ROOT / "setup-state.json"
    if not setup_path.exists():
        raise SetupError("Keep setup-state.json from the successful structure setup in this folder.")
    setup = json.loads(setup_path.read_text(encoding="utf-8"))
    if setup["guild_id"] != config["DISCORD_GUILD_ID"]:
        raise SetupError("The saved connection and structure belong to different servers.")
    reader = DatabaseReader(config["MMA_DASHBOARD_PATH"])
    api = DiscordAPI(config["DISCORD_BOT_TOKEN"])
    path = ROOT / "sync-state.json"
    overrides_path = ROOT / "event-overrides.json"
    with sync_lock():
        now = datetime.now(timezone.utc)
        previous = load_state(path)
        if not args.preview:
            reader.wait_for_daily_sync(now)
        data = fetch_data(reader, now, previous, require_ready=not args.preview)
        if args.preview:
            start, end = week_window(now)
            print(f"Preview: {start} through {end - timedelta(days=1)} (Central Time)")
            for event in data["events"]:
                if local_day(event) and start <= local_day(event) < end:
                    print(event["event_name"] + " — " + ct_time(event.get("event_start_time")))
            print("No Discord changes were made.")
            return
        overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
        with publisher_lease(reader,setup["guild_id"]) as ensure:
            publisher=Publisher(api,setup,path);publisher.ensure_publisher=ensure
            publish_cycle(publisher,data,now,overrides)


if __name__ == "__main__":
    try:
        main()
    except (SetupError, ValueError, KeyError, OSError) as error:
        print("Update stopped: " + str(error), file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("Updater stopped.")
