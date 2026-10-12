from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any


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
    first_numbers, second_numbers = _numbers(a), _numbers(b)
    if first_numbers and second_numbers and not first_numbers.intersection(second_numbers):
        return 0.0
    sequence = SequenceMatcher(None, a, b).ratio()
    tokens_a, tokens_b = set(a.split()), set(b.split())
    overlap = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    return sequence * 0.65 + overlap * 0.35


class OfficialCatalogImporter:
    def __init__(self, supabase: Any) -> None:
        self.supabase = supabase
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

    def _mapping(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        response = (
            self.supabase.table("external_ids")
            .select("external_id_map_id,internal_id")
            .eq("entity_type", "event")
            .eq("source_id", self.sources[entry["promotion_key"]])
            .eq("external_id", entry["external_id"])
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

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
        candidates = [
            (event_match_score(entry["name"], row["event_name"]), row)
            for row in self._events_near(entry)
        ]
        candidates = [row for row in candidates if row[0] >= 0.64]
        candidates.sort(key=lambda row: row[0], reverse=True)
        if not candidates:
            return None
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.08:
            return None
        return int(candidates[0][1]["event_id"])

    def _attach(self, entry: dict[str, Any], event_id: int) -> None:
        source_id = self.sources[entry["promotion_key"]]
        payload = {
            "entity_type": "event",
            "internal_id": event_id,
            "source_id": source_id,
            "external_id": entry["external_id"],
            "external_url": entry.get("external_url"),
            "updated_at": utc_now(),
        }
        existing = (
            self.supabase.table("external_ids")
            .select("external_id_map_id")
            .eq("entity_type", "event")
            .eq("internal_id", event_id)
            .eq("source_id", source_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            self.supabase.table("external_ids").update(payload).eq(
                "external_id_map_id", existing.data[0]["external_id_map_id"]
            ).execute()
            return
        self.supabase.table("external_ids").insert(payload).execute()

    def import_event(self, entry: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        mapping = self._mapping(entry)
        event_id = int(mapping["internal_id"]) if mapping else self._find_existing(entry)
        if dry_run:
            return {"status": "matched" if event_id else "missing", "event_id": event_id}
        payload = {
            "promotion_id": self.promotions[entry["promotion_key"]],
            "event_name": entry["name"],
            "event_date": entry["date"].isoformat(),
            "event_status": "completed" if entry["date"] < date.today() else "scheduled",
            "updated_at": utc_now(),
        }
        if event_id is None:
            response = self.supabase.table("events").insert(payload).execute()
            if not response.data:
                raise RuntimeError("Official catalog event insert returned no data.")
            event_id = int(response.data[0]["event_id"])
            status = "imported"
        else:
            # The detailed provider owns time, location, platform, and live/final
            # result state. The catalog only repairs identity/name/date.
            response = (
                self.supabase.table("events")
                .update({
                    "event_name": entry["name"],
                    "event_date": entry["date"].isoformat(),
                    "updated_at": utc_now(),
                })
                .eq("event_id", event_id)
                .execute()
            )
            if not response.data:
                raise RuntimeError("Official catalog event update returned no data.")
            status = "matched"
        self._attach(entry, event_id)
        return {"status": status, "event_id": event_id}
