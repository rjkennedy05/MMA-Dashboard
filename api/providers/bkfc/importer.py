from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from . import normalizer
from ..fight_identity import preserve_fight_identity
from ..event_identity import matching_event
from ..atomic import wrap_import_client
from ..persistence import find_identity, save_entity


SOURCE_NAME = "BKFC Official / MMAReg"
SOURCE_ALIASES = (SOURCE_NAME, "BKFC Official", "Bare Knuckle FC Official")
PROMOTION_ALIASES = (
    "BKFC",
    "Bare Knuckle Fighting Championship",
    "Bare Knuckle FC",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode(
        "ascii", "ignore"
    ).decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.casefold()).strip()


def split_name(full_name: str) -> tuple[str, str | None]:
    parts = full_name.strip().split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else None


class BkfcImporter:
    def __init__(self, supabase_client: Any) -> None:
        self.supabase = wrap_import_client(supabase_client)
        self.source_id = self._get_source_id()
        self.promotion_id = self._get_promotion_id()

    def _get_source_id(self) -> int:
        for name in SOURCE_ALIASES:
            response = (
                self.supabase.table("data_sources")
                .select("source_id")
                .eq("name", name)
                .limit(1)
                .execute()
            )
            if response.data:
                return int(response.data[0]["source_id"])
        raise RuntimeError(
            "BKFC Official / MMAReg is missing from data_sources. "
            "Run migration 202608030015_add_bkfc.sql."
        )

    def _get_promotion_id(self) -> int:
        response = self.supabase.table("promotions").select(
            "promotion_id, name"
        ).execute()
        aliases = {normalized_name(alias) for alias in PROMOTION_ALIASES}
        for row in response.data or []:
            if normalized_name(row["name"]) in aliases:
                return int(row["promotion_id"])
        raise RuntimeError("BKFC promotion row was not found.")

    def _external_mapping(self, entity_type: str, external_id: str):
        return find_identity(self.supabase, entity_type, self.source_id, external_id)

    def _attach_mapping(
        self,
        entity_type: str,
        internal_id: int,
        external_id: str,
        external_url: str | None = None,
    ) -> None:
        save_entity(self.supabase,entity_type,{},self.source_id,external_id,internal_id,external_url)

    @lru_cache(maxsize=1)
    def _fighter_rows(self) -> list[dict[str, Any]]:
        response = self.supabase.table("fighters").select(
            "fighter_id, full_name"
        ).execute()
        return response.data or []

    def _find_fighter_by_name(self, full_name: str) -> int | None:
        exact = [
            row
            for row in self._fighter_rows()
            if normalized_name(row["full_name"]) == normalized_name(full_name)
        ]
        if len(exact) > 1:
            raise RuntimeError(f"Multiple fighters match BKFC name: {full_name}")
        return int(exact[0]["fighter_id"]) if exact else None

    def _repair_mapped_fighter_name(
        self,
        fighter_id: int,
        official_name: str,
        external_id: str,
    ) -> None:
        response = (
            self.supabase.table("fighters")
            .select("fighter_id, full_name")
            .eq("fighter_id", fighter_id)
            .limit(1)
            .execute()
        )
        if not response.data:
            return
        current_name = response.data[0].get("full_name")
        if not normalizer.is_outcome_control_label(current_name):
            return
        if normalizer.is_outcome_control_label(official_name):
            return
        first_name, last_name = split_name(official_name)
        save_entity(self.supabase, "fighter", {
            "first_name": first_name, "last_name": last_name, "full_name": official_name,
        }, self.source_id, external_id, fighter_id)
        self._fighter_rows.cache_clear()

    def get_or_create_fighter(self, fighter: dict[str, Any]) -> int:
        mapping = self._external_mapping("fighter", fighter["external_id"])
        page_mapping = None
        page = urlparse(str(fighter.get("external_url") or ""))
        if (page.scheme == "https" and page.netloc in {"www.bkfc.com", "bkfc.com"}
                and not page.query and not page.fragment):
            slug = re.fullmatch(r"/fighters/([a-zA-Z0-9_-]+)/?", page.path)
            if slug:
                page_mapping = self._external_mapping("fighter", slug[1])
        if mapping and page_mapping and mapping["internal_id"] != page_mapping["internal_id"]:
            raise RuntimeError("BKFC fighter page and results identities disagree; saved participants were retained.")
        if not mapping and page_mapping:
            fighter_id = int(page_mapping["internal_id"])
            self._attach_mapping("fighter", fighter_id, fighter["external_id"], fighter.get("external_url"))
            self._repair_mapped_fighter_name(fighter_id, fighter["name"], fighter["external_id"])
            return fighter_id
        if mapping:
            fighter_id = int(mapping["internal_id"])
            self._repair_mapped_fighter_name(fighter_id, fighter["name"], fighter["external_id"])
            return fighter_id
        fighter_id = self._find_fighter_by_name(fighter["name"])
        first_name, last_name = split_name(fighter["name"])
        payload = {"first_name": first_name, "last_name": last_name,
                   "full_name": fighter["name"], "status": "active", **{}}
        result = save_entity(self.supabase, "fighter", payload, self.source_id,
                             fighter["external_id"], fighter_id, fighter.get("external_url"))
        fighter_id = int(result["internal_id"])
        self._fighter_rows.cache_clear()
        return fighter_id

    def _find_existing_event(self, name: str, event_date: str):
        rows = self.supabase.table("events").select("event_id,event_name").eq(
            "promotion_id", self.promotion_id).eq("event_date", event_date).execute().data or []
        return matching_event(rows, name, 'bkfc')

    def import_event(
        self,
        event: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        external_id = normalizer.event_external_id(event)
        name = normalizer.event_name(event)
        event_date = normalizer.dashboard_event_date(event).isoformat()
        mapping = self._external_mapping("event", external_id)
        event_data = {
            "promotion_id": self.promotion_id,
            "event_name": name,
            "event_date": event_date,
            "event_start_time": normalizer.event_datetime(event).isoformat(),
            "event_status": normalizer.event_status(event),
            "watch_platform": event.get("watch_platform"),
            **normalizer.event_location(event),
            "updated_at": utc_now(),
        }

        if dry_run:
            return {
                "status": "dry_run",
                "event_id": int(mapping["internal_id"]) if mapping else None,
            }

        event_id = (int(mapping["internal_id"]) if mapping else self._find_existing_event(name, event_date))
        result = save_entity(self.supabase, "event", {key: value for key, value in event_data.items() if value is not None}, self.source_id,
                             external_id, event_id, normalizer.event_external_url(event))
        return {"status": result["status"], "event_id": int(result["internal_id"])}

    @lru_cache(maxsize=1)
    def _weight_classes(self) -> list[dict[str, Any]]:
        response = self.supabase.table("weight_classes").select(
            "weight_class_id, name, gender"
        ).execute()
        return response.data or []

    def _weight_class_id(self, raw_name: str | None) -> int | None:
        if not raw_name:
            return None
        name = raw_name.strip()
        explicit_gender: str | None = None
        lowered = name.casefold()
        for prefix in ("women's ", "womens ", "women "):
            if lowered.startswith(prefix):
                explicit_gender = "Women"
                name = name[len(prefix):].strip()
                break
        matches = [
            row
            for row in self._weight_classes()
            if normalized_name(row["name"]) == normalized_name(name)
            and (
                explicit_gender is None
                or row["gender"].casefold() == explicit_gender.casefold()
            )
        ]
        return int(matches[0]["weight_class_id"]) if len(matches) == 1 else None

    def _find_existing_fight(
        self,
        event_id: int,
        fighter_a_id: int,
        fighter_b_id: int,
    ) -> int | None:
        response = (
            self.supabase.table("fights")
            .select("fight_id, fighter_a_id, fighter_b_id")
            .eq("event_id", event_id)
            .execute()
        )
        target = {fighter_a_id, fighter_b_id}
        for row in response.data or []:
            if {int(row["fighter_a_id"]), int(row["fighter_b_id"])} == target:
                return int(row["fight_id"])
        return None

    def import_fight(
        self,
        event_id: int,
        fight: dict[str, Any],
        fight_order: int,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        external_id = normalizer.fight_external_id(fight)
        mapping = self._external_mapping("fight", external_id)
        fighter_a, fighter_b = normalizer.fighters(fight)

        if dry_run:
            return {
                "status": "dry_run",
                "fight_id": int(mapping["internal_id"]) if mapping else None,
                "fight_status": normalizer.normalized_status(fight),
            }

        fighter_a_id = self.get_or_create_fighter(fighter_a)
        fighter_b_id = self.get_or_create_fighter(fighter_b)
        winner_external_id = normalizer.winner_external_id(fight)
        winner_id = None
        if winner_external_id == fighter_a["external_id"]:
            winner_id = fighter_a_id
        elif winner_external_id == fighter_b["external_id"]:
            winner_id = fighter_b_id

        fight_status = normalizer.normalized_status(fight)
        fight_data = {
            "event_id": event_id,
            "fighter_a_id": fighter_a_id,
            "fighter_b_id": fighter_b_id,
            "weight_class_id": self._weight_class_id(fight.get("weight_class")),
            "scheduled_rounds": fight.get("scheduled_rounds") or 5,
            "fight_order": fight_order,
            "fight_status": fight_status,
            "is_title_fight": bool(fight.get("is_title_fight")),
            "ruleset": fight.get("ruleset") or "Bare Knuckle Boxing",
            "bout_type": fight.get("bout_type"),
            "updated_at": utc_now(),
        }
        if fight_status in {"completed", "draw", "no_contest"}:
            fight_data.update(
                {
                    "winner_id": winner_id,
                    "result_type": fight.get("result_type"),
                    "method": fight.get("method"),
                    "finish_round": fight.get("finish_round"),
                    "finish_time_seconds": fight.get("finish_time_seconds"),
                }
            )

        fight_id = (int(mapping["internal_id"]) if mapping else
                    self._find_existing_fight(event_id, fighter_a_id, fighter_b_id))
        if fight_id is not None:
            fight_data = preserve_fight_identity(self.supabase, fight_id, fight_data)
        result = save_entity(self.supabase, "fight", fight_data, self.source_id,
                             external_id, fight_id, fight.get("external_url"))
        return {"status": result["status"], "fight_id": int(result["internal_id"]),
                "fight_status": result["row"]["fight_status"]}
