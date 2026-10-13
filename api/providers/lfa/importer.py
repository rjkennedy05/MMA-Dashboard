from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from . import normalizer


SOURCE_NAME = "LFA Official / Sherdog"
SOURCE_ALIASES = (SOURCE_NAME, "LFA Composite", "Sherdog LFA")
PROMOTION_ALIASES = ("LFA", "Legacy Fighting Alliance")


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


class LfaImporter:
    def __init__(self, supabase_client: Any) -> None:
        self.supabase = supabase_client
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
            "LFA Official / Sherdog is missing from data_sources. "
            "Run migration 202608030014_add_lfa.sql."
        )

    def _get_promotion_id(self) -> int:
        response = self.supabase.table("promotions").select(
            "promotion_id, name"
        ).execute()
        aliases = {normalized_name(alias) for alias in PROMOTION_ALIASES}
        for row in response.data or []:
            if normalized_name(row["name"]) in aliases:
                return int(row["promotion_id"])
        raise RuntimeError("LFA promotion row was not found.")

    def _external_mapping(
        self,
        entity_type: str,
        external_id: str,
    ) -> dict[str, Any] | None:
        response = (
            self.supabase.table("external_ids")
            .select("external_id_map_id, internal_id")
            .eq("entity_type", entity_type)
            .eq("source_id", self.source_id)
            .eq("external_id", external_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None

    def _attach_mapping(
        self,
        entity_type: str,
        internal_id: int,
        external_id: str,
        external_url: str | None = None,
    ) -> None:
        mapping_data = {
            "entity_type": entity_type,
            "internal_id": internal_id,
            "source_id": self.source_id,
            "external_id": external_id,
            "external_url": external_url,
            "updated_at": utc_now(),
        }
        existing = (
            self.supabase.table("external_ids")
            .select("external_id_map_id")
            .eq("entity_type", entity_type)
            .eq("internal_id", internal_id)
            .eq("source_id", self.source_id)
            .limit(1)
            .execute()
        )
        if existing.data:
            mapping_id = existing.data[0]["external_id_map_id"]
            self.supabase.table("external_ids").update(mapping_data).eq(
                "external_id_map_id", mapping_id
            ).execute()
            return
        self.supabase.table("external_ids").insert(mapping_data).execute()

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
            raise RuntimeError(f"Multiple fighters match LFA name: {full_name}")
        return int(exact[0]["fighter_id"]) if exact else None

    def get_or_create_fighter(self, fighter: dict[str, Any]) -> int:
        mapping = self._external_mapping("fighter", fighter["external_id"])
        if mapping:
            return int(mapping["internal_id"])

        fighter_id = self._find_fighter_by_name(fighter["name"])
        if fighter_id is None:
            first_name, last_name = split_name(fighter["name"])
            inserted = self.supabase.table("fighters").insert(
                {
                    "first_name": first_name,
                    "last_name": last_name,
                    "full_name": fighter["name"],
                    "status": "active",
                }
            ).execute()
            if not inserted.data:
                raise RuntimeError("LFA fighter insert returned no data.")
            fighter_id = int(inserted.data[0]["fighter_id"])
            self._fighter_rows().append(
                {"fighter_id": fighter_id, "full_name": fighter["name"]}
            )

        self._attach_mapping(
            "fighter",
            fighter_id,
            fighter["external_id"],
            fighter.get("external_url"),
        )
        return fighter_id

    def _find_existing_event(self, name: str, event_date: str) -> int | None:
        response = (
            self.supabase.table("events")
            .select("event_id, event_name")
            .eq("promotion_id", self.promotion_id)
            .eq("event_date", event_date)
            .execute()
        )
        rows = response.data or []
        exact = [
            row
            for row in rows
            if normalized_name(row["event_name"]) == normalized_name(name)
        ]
        if exact:
            return int(exact[0]["event_id"])

        lfa_number = re.search(r"\blfa\s*(\d+)\b", normalized_name(name))
        if lfa_number:
            number_matches = [
                row
                for row in rows
                if re.search(
                    rf"\blfa\s*{re.escape(lfa_number.group(1))}\b",
                    normalized_name(row["event_name"]),
                )
            ]
            if len(number_matches) == 1:
                return int(number_matches[0]["event_id"])
        return int(rows[0]["event_id"]) if len(rows) == 1 else None

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
            "event_status": normalizer.event_status(event),
            "watch_platform": normalizer.watch_platform(event),
            **normalizer.event_location(event),
            "updated_at": utc_now(),
        }

        if dry_run:
            return {
                "status": "dry_run",
                "event_id": int(mapping["internal_id"]) if mapping else None,
            }

        if mapping:
            event_id = int(mapping["internal_id"])
            response = (
                self.supabase.table("events")
                .update(event_data)
                .eq("event_id", event_id)
                .execute()
            )
            if not response.data:
                raise RuntimeError("LFA event update returned no data.")
            return {"status": "updated", "event_id": event_id}

        event_id = self._find_existing_event(name, event_date)
        if event_id is None:
            response = self.supabase.table("events").insert(event_data).execute()
            if not response.data:
                raise RuntimeError("LFA event insert returned no data.")
            event_id = int(response.data[0]["event_id"])
            status = "imported"
        else:
            response = (
                self.supabase.table("events")
                .update(event_data)
                .eq("event_id", event_id)
                .execute()
            )
            if not response.data:
                raise RuntimeError("LFA event attachment update returned no data.")
            status = "updated"

        self._attach_mapping(
            "event",
            event_id,
            external_id,
            normalizer.event_external_url(event),
        )
        return {"status": status, "event_id": event_id}

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
            "scheduled_rounds": fight.get("scheduled_rounds") or 3,
            "fight_order": fight_order,
            "fight_status": fight_status,
            "is_title_fight": bool(fight.get("is_title_fight")),
            "ruleset": "MMA",
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

        if mapping:
            fight_id = int(mapping["internal_id"])
            response = (
                self.supabase.table("fights")
                .update(fight_data)
                .eq("fight_id", fight_id)
                .execute()
            )
            if not response.data:
                raise RuntimeError("LFA fight update returned no data.")
            return {
                "status": "updated",
                "fight_id": fight_id,
                "fight_status": fight_status,
            }

        fight_id = self._find_existing_fight(
            event_id, fighter_a_id, fighter_b_id
        )
        if fight_id is None:
            response = self.supabase.table("fights").insert(fight_data).execute()
            if not response.data:
                raise RuntimeError("LFA fight insert returned no data.")
            fight_id = int(response.data[0]["fight_id"])
            status = "imported"
        else:
            response = (
                self.supabase.table("fights")
                .update(fight_data)
                .eq("fight_id", fight_id)
                .execute()
            )
            if not response.data:
                raise RuntimeError("LFA fight attachment update returned no data.")
            status = "updated"

        self._attach_mapping("fight", fight_id, external_id)
        return {
            "status": status,
            "fight_id": fight_id,
            "fight_status": fight_status,
        }
