from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any


GENERATIONAL_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalized_name(value: str | None) -> str:
    without_nickname = re.sub(r'["“][^"”]+["”]', " ", value or "")
    ascii_value = unicodedata.normalize("NFKD", without_nickname).encode("ascii", "ignore").decode()
    tokens = re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip().split()
    while tokens and tokens[-1] in GENERATIONAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def names_compatible(left: str | None, right: str | None) -> bool:
    left_key = normalized_name(left)
    right_key = normalized_name(right)
    if not left_key or not right_key:
        return False
    if left_key == right_key:
        return True
    left_tokens = left_key.split()
    right_tokens = right_key.split()
    shorter, longer = (
        (left_tokens, right_tokens)
        if len(left_tokens) <= len(right_tokens)
        else (right_tokens, left_tokens)
    )
    return (
        len(shorter) >= 2
        and shorter[-1] == longer[-1]
        and all(token in longer for token in shorter)
    )


def partition_dates_for_plan(
    relevant_dates: list[str],
    today: date,
    provider_future_days: int = 1,
) -> tuple[list[str], list[str]]:
    """Keep free-plan requests to today/tomorrow while retaining audit visibility."""

    cutoff = today + timedelta(days=max(provider_future_days, 0))
    eligible: list[str] = []
    deferred: list[str] = []
    for value in relevant_dates:
        parsed = date.fromisoformat(str(value)[:10])
        (eligible if parsed <= cutoff else deferred).append(str(value))
    return eligible, deferred


def decimal_to_american(value: Any) -> int | None:
    try:
        decimal = float(value)
    except (TypeError, ValueError):
        return None
    if decimal <= 1:
        return None
    return round((decimal - 1) * 100) if decimal >= 2 else round(-100 / (decimal - 1))


def _fighter_pair(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    containers = [row]
    if isinstance(row.get("fight"), dict):
        containers.append(row["fight"])

    for container in containers:
        fighters = container.get("fighters") or container.get("teams") or {}
        if isinstance(fighters, list):
            items = fighters + [{}, {}]
            if items[0] or items[1]:
                return items[0] or {}, items[1] or {}
        if isinstance(fighters, dict):
            first = (
                fighters.get("first")
                or fighters.get("home")
                or fighters.get("red")
                or container.get("home")
                or {}
            )
            second = (
                fighters.get("second")
                or fighters.get("away")
                or fighters.get("blue")
                or container.get("away")
                or {}
            )
            if first or second:
                return first, second
    return {}, {}


def _name(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    return str(value.get("name") or value.get("full_name") or " ".join(filter(None, (value.get("firstname"), value.get("lastname"))))).strip()


def normalize_odds_fight(row: dict[str, Any]) -> dict[str, Any] | None:
    fight = row.get("fight") or row
    first, second = _fighter_pair(row)
    home_name, away_name = _name(first), _name(second)
    commence = fight.get("date") or fight.get("time") or row.get("date")
    if not commence:
        return None
    bookmakers_out = []
    for bookmaker in row.get("bookmakers") or row.get("odds") or []:
        title = bookmaker.get("name") or bookmaker.get("title")
        if not title:
            continue
        outcomes = []
        markets = bookmaker.get("bets") or bookmaker.get("markets") or []
        for market in markets:
            market_name = normalized_name(str(market.get("name") or market.get("key") or ""))
            if market_name and not any(token in market_name for token in ("winner", "moneyline", "match winner", "h2h")):
                continue
            for value in market.get("values") or market.get("outcomes") or []:
                selection = value.get("value") or value.get("name")
                raw_price = value.get("odd") if value.get("odd") is not None else value.get("price")
                price = decimal_to_american(raw_price)
                if selection and price is not None:
                    outcomes.append({"name": selection, "price": price})
        if outcomes:
            bookmakers_out.append({
                "key": str(bookmaker.get("id") or normalized_name(title)).replace(" ", "_"),
                "title": title,
                "last_update": row.get("update") or datetime.now(timezone.utc).isoformat(),
                "markets": [{"key": "h2h", "outcomes": outcomes}],
            })
    if not home_name or not away_name:
        market_names: list[str] = []
        for bookmaker in bookmakers_out:
            for market in bookmaker["markets"]:
                for outcome in market["outcomes"]:
                    selection = str(outcome.get("name") or "").strip()
                    if selection and selection not in market_names:
                        market_names.append(selection)
        if len(market_names) >= 2:
            home_name, away_name = market_names[:2]
    if not home_name or not away_name:
        return None
    external_id = str(fight.get("id") or row.get("id") or hashlib.sha1(f"{commence}|{home_name}|{away_name}".encode()).hexdigest()[:20])
    return {
        "id": f"api-sports-{external_id}",
        "commence_time": str(commence),
        "home_team": home_name,
        "away_team": away_name,
        "bookmakers": bookmakers_out,
    }


def normalize_history(rows: list[dict[str, Any]], fighter: dict[str, Any]) -> list[dict[str, Any]]:
    fighter_id = str(fighter.get("id"))
    fighter_key = normalized_name(_name(fighter))
    history = []
    for row in rows:
        fight = row.get("fight") or row
        first, second = _fighter_pair(row)
        first_id, second_id = str(first.get("id")), str(second.get("id"))
        first_key, second_key = normalized_name(_name(first)), normalized_name(_name(second))
        if fighter_id == first_id or fighter_key == first_key:
            opponent, selected_side = second, "first"
        elif fighter_id == second_id or fighter_key == second_key:
            opponent, selected_side = first, "second"
        else:
            continue
        result = row.get("results") or row.get("result") or fight.get("result") or {}
        winner = str(result.get("winner") or result.get("winner_id") or "")
        outcome = "—"
        if winner:
            won = winner in {fighter_id, selected_side, _name(fighter)}
            outcome = "W" if won else "L"
        status = normalized_name(str(fight.get("status") or row.get("status") or ""))
        if "cancel" in status:
            outcome = "CANCELLED"
        elif "draw" in status:
            outcome = "D"
        elif "no contest" in status:
            outcome = "NC"
        league = row.get("league") or fight.get("league") or {}
        event_name = fight.get("name") or row.get("name") or (league.get("name") if isinstance(league, dict) else league)
        method = result.get("method") or fight.get("method")
        round_value = result.get("round") or fight.get("round")
        time_value = result.get("time") or fight.get("time")
        seconds = None
        if isinstance(time_value, str) and re.match(r"^\d+:\d{2}$", time_value):
            minutes, secs = time_value.split(":")
            seconds = int(minutes) * 60 + int(secs)
        external_id = str(fight.get("id") or row.get("id") or hashlib.sha1(str(row).encode()).hexdigest()[:20])
        history.append({
            "external_bout_id": f"api-sports-{external_id}",
            "source_url": None,
            "event_name": event_name,
            "event_date": str(fight.get("date") or row.get("date") or "")[:10] or None,
            "promotion_name": league.get("name") if isinstance(league, dict) else league,
            "opponent_name": _name(opponent),
            "opponent_record": opponent.get("record") if isinstance(opponent, dict) else None,
            "outcome": outcome,
            "method": method,
            "finish_round": int(round_value) if str(round_value or "").isdigit() else None,
            "finish_time_seconds": seconds,
            "fight_status": "cancelled" if outcome == "CANCELLED" else "completed",
            "is_title_fight": bool(fight.get("title") or row.get("is_title_fight")),
        })
    return [entry for entry in history if entry["opponent_name"]]
