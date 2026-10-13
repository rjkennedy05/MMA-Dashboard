"""Fetch one event directly. No database clients or database writes."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import time
from urllib.parse import urlparse

from setup_discord import SetupError
from sync_discord import normalized, parsed_time, promotion, local_day, status
from provider_runtime import ARCHIVED_PROMOTIONS, provider_module


class SourceError(SetupError):
    def __init__(self, message, http_status=None):
        super().__init__(message)
        self.http_status = http_status


HOSTS = {
    "site.api.espn.com", "site.web.api.espn.com", "sports.core.api.espn.com",
    "www.onefc.com", "www.lfa.com", "www.sherdog.com", "www.bkfc.com",
    "xapi.mmareg.com", "api.the-odds-api.com",
}
PROVIDERS = {"ufc": "espn_mma", "dwcs": "espn_mma", "pfl": "espn_mma",
             "one": "one_championship", "lfa": "lfa", "bkfc": "bkfc"}


class ReaderSession:
    """Bounded public reads; credentials never follow a redirect."""
    def __init__(self, hosts=None, seconds=150):
        import requests
        self.session = requests.Session()
        self.hosts = set(hosts or HOSTS)
        self.deadline = time.monotonic() + seconds
        self.calls = 0

    def get(self, url, **kwargs):
        parsed = urlparse(url)
        if (parsed.hostname not in self.hosts or parsed.username or parsed.password
                or parsed.port not in (None, 443, 80) or parsed.scheme not in {"https", "http"}):
            raise SourceError("The provider returned an unexpected source address.")
        if parsed.scheme == "http":
            url = "https:" + url[5:]
        remaining = self.deadline - time.monotonic()
        if remaining < 1 or self.calls >= 60:
            raise SourceError("The source check took too long. Saved information was kept; try again later.")
        self.calls += 1
        kwargs["timeout"] = min(float(kwargs.get("timeout", 20)), 20, remaining)
        kwargs["allow_redirects"] = False
        kwargs["stream"] = True
        response = self.session.get(url, **kwargs)
        if 300 <= response.status_code < 400:
            response.close()
            raise SourceError("The source redirected this check. Saved information was kept.")
        if response.status_code >= 400:
            code = response.status_code
            response.close()
            raise SourceError(f"The source is unavailable (HTTP {code}). Saved information was kept.", http_status=code)
        chunks, size = [], 0
        try:
            for chunk in response.iter_content(65536):
                if time.monotonic() > self.deadline:
                    raise SourceError("The source check took too long. Saved information was kept.")
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise SourceError("The source response was too large to use safely.")
                chunks.append(chunk)
            response._content = b"".join(chunks)
            response._content_consumed = True
        finally:
            response.close()
        return response

    def close(self):
        self.session.close()


def safe_source_url(value, hosts, pattern=None):
    try:
        parsed = urlparse(str(value or ""))
        if (parsed.scheme == "https" and parsed.hostname in hosts and not parsed.username
                and not parsed.password and parsed.port in (None, 443)
                and (not pattern or re.search(pattern, parsed.path))):
            return str(value)
    except ValueError:
        pass
    return None


def title_kind(value):
    text = normalized(value)
    for token in ("friday fights", "fight night", "inner circle", "contender series"):
        if token in text:
            return token
    return ""


def select_event(event, listings):
    """Require a unique title/date match, never guess between same-day ONE cards."""
    matcher = provider_module("fightodds", "normalizer")
    candidates = []
    for row in listings:
        name = row.get("name") or row.get("event_name") or ""
        left, right = title_kind(event.get("event_name")), title_kind(name)
        if left and right and left != right:
            continue
        numbers_a = set(re.findall(r"\d+", normalized(event.get("event_name"))))
        numbers_b = set(re.findall(r"\d+", normalized(name)))
        if numbers_a and numbers_b and not numbers_a.intersection(numbers_b):
            continue
        current = row.get("date")
        if isinstance(current, datetime):
            current = current.date()
        if isinstance(current, date) and local_day(event) and abs((current - local_day(event)).days) > 2:
            continue
        score = matcher.event_match_score(event.get("event_name") or "", name)
        if score >= 0.72:
            candidates.append((score, row))
    candidates.sort(key=lambda row: row[0], reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.05):
        raise SourceError("No unique external event matched this card. Add its source URL in event-overrides.json.")
    return candidates[0][1]


def strict_pair(first, second, fights):
    matcher = provider_module("fightodds", "normalizer")
    candidates = []
    for fight in fights:
        a = (fight.get("fighter_a") or {}).get("full_name") or ""
        b = (fight.get("fighter_b") or {}).get("full_name") or ""
        forward = (matcher.name_similarity(first, a), matcher.name_similarity(second, b))
        reverse = (matcher.name_similarity(first, b), matcher.name_similarity(second, a))
        orientation = "forward" if sum(forward) >= sum(reverse) else "reverse"
        scores = forward if orientation == "forward" else reverse
        if min(scores) >= 0.90:
            candidates.append((sum(scores), fight, orientation))
    candidates.sort(key=lambda row: row[0], reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08):
        return None
    return candidates[0][1], candidates[0][2]


def synthetic_id(provider, value):
    return str(10 ** 30 + int(hashlib.sha256(f"{provider}:{value}".encode()).hexdigest()[:20], 16))


def convert_fights(provider, event, rows, previous, identities=None):
    identities = deepcopy(identities or {})
    converted = []
    for index, row in enumerate(rows, 1):
        a, b = row["fighter_a"], row["fighter_b"]
        if not a.get("name") or not b.get("name") or normalized(a["name"]) == normalized(b["name"]):
            raise SourceError("The source returned an incomplete fighter pairing. Saved information was kept.")
        pair = strict_pair(a["name"], b["name"], previous)
        source_key = provider + ":" + str(row["external_id"])
        same_source = [f for f in previous if f.get("_source_fight") == source_key]
        old = pair[0] if pair else same_source[0] if len(same_source) == 1 else None
        fight_id = old["fight_id"] if old else synthetic_id(provider, row["external_id"])
        fighters = []
        paired = [old.get("fighter_a") or {}, old.get("fighter_b") or {}] if pair else [{}, {}]
        if pair and pair[1] == "reverse":
            paired.reverse()
        for position, side in enumerate((a, b)):
            identity_key = provider + ":" + str(side["external_id"])
            known = [s for f in previous for s in (f.get("fighter_a") or {}, f.get("fighter_b") or {})
                     if normalized(s.get("full_name")) == normalized(side["name"])]
            unique = {str(s["fighter_id"]): s for s in known if s.get("fighter_id") is not None}
            fighter_id = identities.get(identity_key)
            if fighter_id is None:
                fighter_id = paired[position].get("fighter_id")
            if fighter_id is None:
                fighter_id = next(iter(unique)) if len(unique) == 1 else synthetic_id(provider, side["external_id"])
            identities[identity_key] = str(fighter_id)
            fighters.append({"fighter_id": fighter_id, "full_name": side["name"]})
        fight_status = row.get("fight_status") or "scheduled"
        winner = next((fighters[i]["fighter_id"] for i, side in enumerate((a, b)) if side.get("winner")), None)
        old_status = status((old or {}).get("fight_status"))
        # A missing outcome marker must not erase a previously confirmed outcome.
        missing_result = status(fight_status) != "completed" or (
            winner is None and normalized(row.get("result_type")) not in {"draw", "no contest"})
        if old and old_status == "completed" and missing_result:
            result = deepcopy(old)
            result["_source_fight"] = source_key
            converted.append(result)
            continue
        base = deepcopy(old or {})
        base.update(fight_id=fight_id, event_id=event["event_id"],
                    fighter_a=fighters[0], fighter_b=fighters[1],
                    fighter_a_id=fighters[0]["fighter_id"], fighter_b_id=fighters[1]["fighter_id"],
                    fight_order=row.get("fight_order", index), fight_status=fight_status,
                    winner_id=winner, method=row.get("method"), result_type=row.get("result_type"),
                    finish_round=row.get("finish_round"), finish_time_seconds=row.get("finish_time_seconds"),
                    _source_fight=source_key)
        for key in ("ruleset", "bout_type"):
            if row.get(key):
                base[key] = row[key]
        if row.get("weight_class"):
            base["weight_classes"] = {"name": row["weight_class"]}
        converted.append(base)
    if not converted:
        raise SourceError("The source did not publish a usable fight card. Saved information was kept.")
    ids = [str(f["fight_id"]) for f in converted]
    if len(ids) != len(set(ids)):
        raise SourceError("The source returned ambiguous duplicate matchups. Saved information was kept.")
    return converted, identities


def _seed(event, source_url, key):
    instant = parsed_time(event.get("event_start_time"))
    if not instant:
        day = local_day(event)
        if not day:
            raise SourceError("This event needs a confirmed date before it can be matched externally.")
        instant = datetime.combine(day, datetime.min.time(), timezone.utc)
    return {"external_id": key, "name": event["event_name"], "date": instant, "_seed_only": True,
            "external_url": source_url, "status": event.get("event_status") or "upcoming"}


def _page_time(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(node.get_text())
            rows = value if isinstance(value, list) else [value] + (value.get("@graph", []) if isinstance(value, dict) else [])
            for row in rows:
                if isinstance(row, dict) and row.get("@type") in ("Event", "SportsEvent"):
                    instant = parsed_time(row.get("startDate"))
                    if instant:
                        return instant
        except (ValueError, TypeError):
            continue
    return None


def _merge_event(event, raw, n, now, html="", allow_status=True):
    result = deepcopy(event)
    location = n.event_location(raw)
    result.update({k: v for k, v in location.items() if k in {"city", "state_region", "country"} and v})
    watch = n.watch_platform(raw) if hasattr(n, "watch_platform") else raw.get("watch_platform")
    if watch:
        result["watch_platform"] = watch
    instant = _page_time(html) if html else None
    instant = instant or raw.get("date_time")
    if not instant and not raw.get("_seed_only") and isinstance(raw.get("date"), (datetime, str)):
        instant = raw["date"]
    if isinstance(instant, str):
        instant = parsed_time(instant)
    if isinstance(instant, datetime) and instant.tzinfo:
        from sync_discord import chicago
        result.update(event_start_time=instant.astimezone(timezone.utc).isoformat(),
                      event_date=instant.astimezone(chicago()).date().isoformat())
    if allow_status and status(event.get("event_status")) != "completed":
        result["event_status"] = n.event_status(raw)
    result["updated_at"] = now.isoformat()
    return result


def _bkfc_listed_event(event, client, n):
    groups, failures = [], []
    for read, state in ((client.get_upcoming, "upcoming"), (client.get_past, "completed")):
        try:
            groups.append(n.parse_event_listing(read(), state))
        except (SourceError, ValueError, RuntimeError) as error:
            failures.append(error)
    if not groups:
        if failures and isinstance(failures[0], SourceError):
            raise failures[0]
        raise SourceError("BKFC's event listings could not be read. Saved information was kept.")
    return select_event(event, n.merge_event_listings(*groups))


def fetch_fight_card(event, previous, links, now, override=None, identities=None, names=None):
    """Return a normalized external snapshot. The caller commits only after success."""
    override = override or {}
    key = promotion(event)
    if key in ARCHIVED_PROMOTIONS:
        raise SourceError("RIZIN tracking is retired; saved dashboard and Discord history remains available.")
    provider = PROVIDERS.get(key)
    if not provider:
        raise SourceError("This event's promotion has no direct source reader.")
    n, module = provider_module(provider, "normalizer"), provider_module(provider, "client")
    urls = [override.get("source_url")] + [r.get("external_url") if isinstance(r, dict) else r for r in links or []]
    session = ReaderSession()
    warnings = []
    stage = "external fight source"
    try:
        if provider == "espn_mma":
            client = module.EspnMmaClient(league="pfl" if key == "pfl" else "ufc", session=session, timeout=20)
            source_id = None
            for url in urls:
                safe = safe_source_url(url, {"www.espn.com", "espn.com", "site.web.api.espn.com", "sports.core.api.espn.com"})
                match = re.search(r"(?:/id/|/fightcenter/|/events/)(\d+)", safe or "")
                if match:
                    source_id = match[1]
                    break
            if source_id:
                center = client.get_fightcenter(source_id)
                raw = center.get("event") if isinstance(center.get("event"), dict) else {}
                raw = {"id": source_id, "name": event["event_name"], "date": event.get("event_start_time"), **raw}
            else:
                day = local_day(event)
                if not day:
                    raise SourceError("A date is needed to locate this event on ESPN.")
                listings = client.get_events_in_window(day - timedelta(days=2), day + timedelta(days=2))
                if key != "pfl":
                    listings = [row for row in listings if n.event_promotion_key(row) == key]
                raw = select_event(event, listings)
                source_id = n.event_external_id(raw)
                center = client.get_fightcenter(source_id)
            rows = []
            original = n.event_fights(raw, center)
            for index, fight in enumerate(original, 1):
                if n.is_placeholder_fight(fight):
                    continue
                a, b = n.fighters(fight)
                rows.append({"external_id": n.fight_external_id(fight), "fighter_a": a, "fighter_b": b,
                             "fight_order": index, "fight_status": n.normalized_status(fight),
                             "ruleset": "MMA", "weight_class": n.weight_class(fight),
                             "result_type": n.result_type(fight), "method": n.finish_method(fight),
                             "finish_round": n.finish_round(fight), "finish_time_seconds": n.finish_time_seconds(fight)})
            source_url = f"https://www.espn.com/mma/fightcenter/_/id/{source_id}"
            update = _merge_event(event, raw, n, now, allow_status=bool(raw.get("status")))
            complete = len(rows) == len(original)
        elif key == "one":
            client = module.OneChampionshipClient(session=session, timeout=20)
            source_url = next((u for u in urls if safe_source_url(u, {"www.onefc.com"}, r"^/events/[^/]+")), None)
            if source_url:
                raw = _seed(event, source_url, urlparse(source_url).path.strip("/").split("/")[-1])
            else:
                raw = select_event(event, n.parse_event_listing(client.get_event_listing()))
                source_url = n.event_external_url(raw)
            html = client.get_event_page(source_url)
            status_url = n.event_status_url(html)
            status_data = client.get_event_status(status_url) if status_url else None
            raw = n.enrich_event(raw, html, status_data)
            rows = n.parse_fights(raw, html)
            from bs4 import BeautifulSoup
            complete = len(rows) == len(BeautifulSoup(html, "html.parser").select(".event-matchup"))
            update = _merge_event(event, raw, n, now, html, allow_status=bool(status_data))
        elif key == "lfa":
            client = module.LfaClient(session=session, timeout=20)
            source_url = next((u for u in urls if safe_source_url(u, {"www.sherdog.com"}, r"^/events/")), None)
            if source_url:
                match = re.search(r"\blfa\s+(\d+)\b", normalized(event["event_name"]))
                raw = _seed(event, source_url, "lfa-" + match[1] if match else source_url)
            else:
                raw = select_event(event, n.parse_sherdog_index(client.get_sherdog_index()))
                source_url = n.sherdog_event_url(raw)
            html = client.get_sherdog_event(source_url)
            rows = n.parse_sherdog_fights(raw, html)
            update = _merge_event(event, raw, n, now, html, allow_status=False)
            complete = True
        elif key == "bkfc":
            client = module.BkfcClient(session=session, timeout=20)
            stage = "BKFC event listing"
            source_url = next((u for u in urls if safe_source_url(u, {"www.bkfc.com"}, r"^/(?:events|event)/[^/]+")), None)
            if source_url:
                raw = _seed(event, source_url, urlparse(source_url).path.strip("/").split("/")[-1])
            else:
                raw = _bkfc_listed_event(event, client, n)
                source_url = n.event_external_url(raw)
            stage = "BKFC event page"
            try:
                html = client.get_event_page(source_url)
            except SourceError as error:
                if error.http_status not in {404, 410}:
                    raise
                raw = _bkfc_listed_event(event, client, n)
                replacement_url = n.event_external_url(raw)
                if replacement_url == source_url:
                    raise error
                source_url = replacement_url
                html = client.get_event_page(source_url)
            raw = n.enrich_event(raw, html)
            stats_url = n.event_stats_url(html)
            stats = None
            if stats_url:
                try:
                    stats = client.get_event_stats(stats_url)
                except (SourceError, module.BkfcProviderError):
                    warnings.append("BKFC's results feed is unavailable; the card was read and previous results were kept.")
            rows = n.parse_fights(raw, html, stats)
            if stats and rows:
                matched = sum(bool(row.get("results_source_matched")) for row in rows)
                if matched < len(rows):
                    warnings.append(f"BKFC's results feed matched {matched}/{len(rows)} fights; unmatched outcomes were not inferred.")
            from bs4 import BeautifulSoup
            complete = len(rows) == len(BeautifulSoup(html, "html.parser").select("[data-bout]"))
            update = _merge_event(event, raw, n, now, html, allow_status=False)
        else:
            raise SourceError("This event's promotion has no active direct source reader.")
        fights, identities = convert_fights(provider, event, rows, previous, identities)
        # Large shrinkage is a partial response, not proof of mass cancellations.
        if len(fights) < len(previous) * 0.6:
            complete = False
        if not complete:
            known = {str(f["fight_id"]) for f in fights}
            fights.extend(deepcopy(f) for f in previous if str(f["fight_id"]) not in known)
        if any(status(f.get("fight_status")) == "live" for f in fights):
            update["event_status"] = "live"
        elif fights and all(status(f.get("fight_status")) in {"completed", "cancelled"} for f in fights):
            update["event_status"] = "completed"
        return {"event": update, "fights": fights, "source_url": source_url,
                "source": "ESPN MMA" if provider == "espn_mma" else {"one": "ONE Championship", "lfa": "Sherdog / LFA", "bkfc": "BKFC / MMAReg"}[key],
                "checked_at": now.isoformat(), "complete": complete, "identities": identities, "names": names or {},
                "warnings": list(dict.fromkeys(warnings))}
    except SourceError:
        raise
    except Exception:
        raise SourceError(f"The {stage} could not be read. Saved information was kept; try again later.") from None
    finally:
        session.close()


def _odds_rows(boards, fights, now, source):
    result, covered = [], set()
    for board in boards:
        match = strict_pair(board["fighter_one"], board["fighter_two"], fights)
        if not match:
            continue
        fight, orientation = match
        sides = [fight["fighter_a_id"], fight["fighter_b_id"]]
        if orientation == "reverse":
            sides.reverse()
        for book in board.get("sportsbooks", []):
            name = book.get("sportsbook") or ""
            key = book.get("sportsbook_key") or normalized(name).replace(" ", "")
            if not key or re.search(r"\b(?:best|opening|opener|average|consensus)\b", normalized(name)):
                continue
            for fighter, column in zip(sides, ("fighter_one_odds", "fighter_two_odds")):
                price = book.get(column)
                if isinstance(price, (int, float)) and abs(price) >= 100:
                    result.append({"fight_id": fight["fight_id"], "fighter_id": fighter,
                                   "sportsbook": name, "sportsbook_key": key,
                                   "american_odds": int(price), "recorded_at": now.isoformat(),
                                   "provider_updated_at": book.get("updated_at"), "source": source})
                    covered.add(str(fight["fight_id"]))
    return result, len(covered)


def fetch_odds(event, fights, links, now, override=None, odds_config=None):
    active = [f for f in fights if status(f.get("fight_status")) in {"scheduled", "live"}]
    if not active:
        raise SourceError("There are no active matchups to check for odds on this card.")
    override, odds_config = override or {}, odds_config or {}
    n, module = provider_module("fightodds", "normalizer"), provider_module("fightodds", "client")
    urls = [override.get("odds_url")] + [r.get("external_url") if isinstance(r, dict) else r for r in links or []]
    try:
        odds_url = next((u for u in urls if safe_source_url(u, {"fightodds.io"}, r"^/(?:mma-events|odds)/\d+/")), None)
        if odds_url and "/mma-events/" in odds_url:
            odds_url = odds_url.replace("/mma-events/", "/odds/")
        with module.FightOddsClient() as client:
            if not odds_url:
                row = select_event(event, n.parse_upcoming_events(client.get_upcoming_events()))
                odds_url = row["odds_url"]
            boards = n.parse_event_odds(client.get_event_odds(odds_url))
        rows, covered = _odds_rows(boards, active, now, "FightOdds")
        if rows:
            return {"rows": rows, "covered": covered, "total": len(active), "source": "FightOdds",
                    "source_url": odds_url, "checked_at": now.isoformat()}
    except Exception:
        pass
    api_key = odds_config.get("THE_ODDS_API_KEY")
    if not api_key:
        raise SourceError("FightOdds has no usable matching moneylines or could not load. Run 07-INSTALL-COMMANDS.bat if this is the first check; you can also set this event's odds_url.")
    session = ReaderSession(seconds=40)
    try:
        regions = odds_config.get("THE_ODDS_API_REGIONS") or "us"
        response = session.get("https://api.the-odds-api.com/v4/sports/mma_mixed_martial_arts/odds", params={
            "apiKey": api_key, "regions": regions, "markets": "h2h", "oddsFormat": "american", "dateFormat": "iso"})
        payload = response.json()
        if not isinstance(payload, list):
            raise SourceError("The odds provider returned an unusable response.")
        boards = []
        for matchup in payload:
            when = parsed_time(matchup.get("commence_time"))
            if when and local_day(event) and abs((when.date() - local_day(event)).days) > 2:
                continue
            books = []
            first, second = matchup.get("home_team"), matchup.get("away_team")
            for book in matchup.get("bookmakers") or []:
                for market in book.get("markets") or []:
                    if market.get("key") != "h2h":
                        continue
                    prices = {o.get("name"): o.get("price") for o in market.get("outcomes") or []}
                    if first in prices and second in prices:
                        books.append({"sportsbook": book.get("title"), "sportsbook_key": book.get("key"),
                                      "fighter_one_odds": prices[first], "fighter_two_odds": prices[second],
                                      "updated_at": market.get("last_update") or book.get("last_update")})
            boards.append({"fighter_one": first, "fighter_two": second, "sportsbooks": books})
        rows, covered = _odds_rows(boards, active, now, "The Odds API")
        if not rows:
            raise SourceError("Neither odds source published matching moneylines for this event. Saved odds were kept.")
        return {"rows": rows, "covered": covered, "total": len(active), "source": "The Odds API",
                "source_url": "https://the-odds-api.com", "checked_at": now.isoformat(),
                "remaining": response.headers.get("x-requests-remaining")}
    except SourceError:
        raise
    except Exception:
        raise SourceError("The odds source could not be read. Saved prices were kept.") from None
    finally:
        session.close()
