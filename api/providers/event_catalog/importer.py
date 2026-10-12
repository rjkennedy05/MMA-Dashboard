from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any

from ..event_identity import AmbiguousEventError
from ..atomic import wrap_import_client
from ..persistence import find_identity, save_entity


SOURCE_NAMES = {
    "ufc": "UFC Official Event Catalog",
    "dwcs": "UFC Official Event Catalog",
    "pfl": "PFL Official Event Catalog",
}
PROMOTION_ALIASES = {
    "ufc": {"ufc", "ultimate fighting championship"},
    "dwcs": {
        "dwcs",
        "dana white s contender series",
        "dana whites contender series",
        "dana white contender series",
    },
    "pfl": {"pfl", "professional fighters league"},
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", str(value or "")).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def _numbers(value: Any) -> set[str]:
    return set(re.findall(r"\d+", normalized(value)))


def event_match_score(first: str, second: str) -> float:
    a, b = normalized(first), normalized(second)
    if not a or not b:
        return 0.0
    ordinal=r"\b(ufc|lfa|bkfc)\s+(\d+)\b"
    one,two=re.search(ordinal,a),re.search(ordinal,b)
    if one and two and one.group(1)==two.group(1) and one.group(2)!=two.group(2):return 0.0
    first_numbers, second_numbers = _numbers(a), _numbers(b)
    if first_numbers and second_numbers and not first_numbers.intersection(second_numbers):
        return 0.0
    # Official PFL headings can omit the main-event fighters. Require a shared
    # named location/brand prefix; "PFL" or "PFL 2" alone cannot establish identity.
    # The caller still requires the same promotion/date and rejects tied matches.
    if a.startswith("pfl ") and b.startswith("pfl "):
        for short, long in ((a, b), (b, a)):
            prefix = re.sub(r"\s+\d+$", "", short)
            tokens = prefix.split()
            if "vs" in short.split() or "v" in short.split():
                continue
            if len(tokens) >= 2 and not tokens[1].isdigit() and long.startswith(prefix + " "):
                short_edition = re.fullmatch(re.escape(prefix) + r" (\d+)", short)
                long_edition = re.match(re.escape(prefix) + r" (\d+)\b", long)
                if short_edition and long_edition and short_edition[1] != long_edition[1]:
                    return 0.0
                return 0.80
    sequence = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    overlap = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    return sequence * 0.65 + overlap * 0.35


class OfficialCatalogImporter:
    def __init__(self, supabase: Any) -> None:
        self.supabase = wrap_import_client(supabase)
        self.sources = self._source_ids()
        self.promotions = self._promotion_ids()

    def _source_ids(self) -> dict[str, int]:
        rows = self.supabase.table("data_sources").select("source_id,name").execute().data or []
        by_name = {normalized(row["name"]): int(row["source_id"]) for row in rows}
        result = {}
        for key, name in SOURCE_NAMES.items():
            source_id = by_name.get(normalized(name))
            if source_id is None:
                raise RuntimeError(
                    "Official event catalog sources are missing. Run migration "
                    "202610050030_add_event_catalog_sources.sql."
                )
            result[key] = source_id
        return result

    def _promotion_ids(self) -> dict[str, int]:
        rows = self.supabase.table("promotions").select("promotion_id,name").execute().data or []
        result = {}
        for key, aliases in PROMOTION_ALIASES.items():
            matches = [row for row in rows if normalized(row["name"]) in aliases]
            if len(matches) != 1:
                raise RuntimeError(f"The {key.upper()} promotion row could not be resolved uniquely.")
            result[key] = int(matches[0]["promotion_id"])
        return result

    def _mapping(self, entry):
        return find_identity(self.supabase, "event", self.sources[entry["promotion_key"]], entry["external_id"])

    def _events_near(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        event_date = entry["date"]
        response = (
            self.supabase.table("events")
            .select("event_id,event_name,event_date,promotion_id")
            .eq("promotion_id", self.promotions[entry["promotion_key"]])
            .gte("event_date", (event_date - timedelta(days=1)).isoformat())
            .lte("event_date", (event_date + timedelta(days=1)).isoformat())
            .execute()
        )
        return response.data or []

    def _find_existing(self, entry: dict[str, Any]) -> int | None:
        nearby=self._events_near(entry)
        candidates = [
            (event_match_score(entry["name"], row["event_name"]), row)
            for row in nearby
        ]
        candidates = [row for row in candidates if row[0] >= 0.64]
        candidates.sort(key=lambda row: row[0], reverse=True)
        if not candidates:
            if any(str(row.get("event_date") or "")[:10]==entry["date"].isoformat() for row in nearby):
                raise AmbiguousEventError("A stored event already shares this promotion and day. Detailed source identity must resolve the new catalog title before another header is created.")
            return None
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08:
            raise AmbiguousEventError(
                f"Official event {entry['name']} has multiple plausible stored matches; no new event was inserted."
            )
        return int(candidates[0][1]["event_id"])

    def _attach(self, entry: dict[str, Any], event_id: int) -> None:
        save_entity(self.supabase,"event",{},self.sources[entry["promotion_key"]],entry["external_id"],event_id,entry.get("external_url"),catalog=True)

    def import_event(self, entry: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        mapping = self._mapping(entry)
        event_id = int(mapping["internal_id"]) if mapping else self._find_existing(entry)
        if dry_run:
            return {"status": "matched" if event_id else "missing", "event_id": event_id}
        result = save_entity(self.supabase, "event", {
            "promotion_id": self.promotions[entry["promotion_key"]], "event_name": entry["name"],
            "event_date": entry["date"].isoformat(), "updated_at": utc_now(),
        }, self.sources[entry["promotion_key"]], entry["external_id"], event_id,
           entry.get("external_url"), catalog=True)
        return {"status": "imported" if result["status"] == "imported" else "matched",
                "event_id": int(result["internal_id"])}
