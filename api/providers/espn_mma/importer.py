from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from . import normalizer
from ..fight_identity import preserve_fight_identity
from ..event_identity import matching_event
from ..atomic import wrap_import_client
from ..persistence import find_identity, save_entity


SOURCE_NAME = "ESPN MMA"
SOURCE_ALIASES = (SOURCE_NAME, "ESPN")
PFL_ALIASES = ("PFL", "Professional Fighters League")
UFC_ALIASES = ("UFC", "Ultimate Fighting Championship")
DWCS_ALIASES = (
    "DWCS",
    "Dana White's Contender Series",
    "Dana Whites Contender Series",
    "Dana White Contender Series",
)
FIGHTER_FIRST_NAME_ALIASES = {
    "joe": "joseph",
    "tom": "thomas",
}


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


def fighter_name_key(value: str) -> str:
    parts = normalized_name(value).split()
    if parts:
        parts[0] = FIGHTER_FIRST_NAME_ALIASES.get(parts[0], parts[0])
    return " ".join(parts)


class EspnMmaImporter:
    def __init__(
        self,
        supabase_client: Any,
        promotion_aliases: tuple[str, ...],
        promotion_label: str,
    ) -> None:
        self.supabase = wrap_import_client(supabase_client)
        self.promotion_aliases = promotion_aliases
        self.promotion_label = promotion_label
        self.source_id = self._get_source_id()
        self.promotion_id = self._get_promotion_id(promotion_aliases)

    def clear_lookup_caches(self) -> None:
        """Refresh local identity lookups before retrying a partial import."""
        self._fighter_rows.cache_clear()
        self._weight_classes.cache_clear()

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
            "ESPN MMA is missing from data_sources. "
            "Run migration 202608030012_use_espn_for_pfl.sql."
        )

    def _get_promotion_id(
        self,
        promotion_aliases: tuple[str, ...],
    ) -> int:
        response = self.supabase.table("promotions").select(
            "promotion_id, name"
        ).execute()
        aliases = {
            normalized_name(alias)
            for alias in promotion_aliases
        }
        for row in response.data or []:
            if normalized_name(row["name"]) in aliases:
                return int(row["promotion_id"])
        raise RuntimeError(
            f"{self.promotion_label} promotion row was not found."
        )

    def _promotion_id_for_event(
        self,
        event: dict[str, Any],
    ) -> int:
        return self.promotion_id

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
            if fighter_name_key(row["full_name"])
            == fighter_name_key(full_name)
        ]
        # A provider ID is the only safe identity when duplicate local names
        # exist. Returning no name match makes get_or_create_fighter create a
        # dedicated ESPN-mapped row instead of guessing or aborting the card.
        if len(exact) > 1:
            return None
        return int(exact[0]["fighter_id"]) if exact else None

    def get_or_create_fighter(self, fighter: dict[str, Any]) -> int:
        mapping = self._external_mapping("fighter", fighter["external_id"])
        if mapping:
            fighter_id = int(mapping["internal_id"])
            self._update_fighter_profile(fighter_id, fighter)
            return fighter_id
        fighter_id = self._find_fighter_by_name(fighter["name"])
        first_name, last_name = split_name(fighter["name"])
        payload = {"first_name": first_name, "last_name": last_name,
                   "full_name": fighter["name"], "status": "active", **self._fighter_profile_payload(fighter)}
        result = save_entity(self.supabase, "fighter", payload, self.source_id,
                             fighter["external_id"], fighter_id, fighter.get("external_url"))
        fighter_id = int(result["internal_id"])
        self._fighter_rows.cache_clear()
        return fighter_id

    def _fighter_profile_payload(
        self,
        fighter: dict[str, Any],
    ) -> dict[str, Any]:
        profile = fighter.get("profile") or {}
        allowed = {
            "nickname",
            "date_of_birth",
            "height_inches",
            "reach_inches",
            "stance",
            "nationality",
            "record_summary",
            "age_snapshot",
            "image_url",
        }
        payload = {
            key: value
            for key, value in profile.items()
            if key in allowed and value not in (None, "")
        }
        if payload:
            payload.update({
                "profile_source_id": self.source_id,
                "profile_updated_at": utc_now(),
                "updated_at": utc_now(),
            })
        return payload

    def _update_fighter_profile(
        self,
        fighter_id: int,
        fighter: dict[str, Any],
    ) -> None:
        payload = self._fighter_profile_payload(fighter)
        if not payload:
            return
        save_entity(self.supabase, "fighter", payload, self.source_id,
                    fighter["external_id"], fighter_id, fighter.get("external_url"))

    def _find_existing_event(self, name: str, event_date: str, promotion_id: int):
        rows = self.supabase.table("events").select("event_id,event_name").eq(
            "promotion_id", promotion_id).eq("event_date", event_date).execute().data or []
        return matching_event(rows, name, "pfl" if self.promotion_label == "PFL" else "ufc")

    def import_event(
        self,
        event: dict[str, Any],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        external_id = normalizer.event_external_id(event)
        name = normalizer.event_name(event)
        event_date = normalizer.dashboard_event_date(event).isoformat()
        promotion_id = self._promotion_id_for_event(event)
        mapping = self._external_mapping("event", external_id)
        event_data = {
            "promotion_id": promotion_id,
            "event_name": name,
            "event_date": event_date,
            "event_start_time": normalizer.event_datetime(event).isoformat(),
            "event_status": normalizer.event_status(event),
            "watch_platform": normalizer.watch_platform(event),
            **normalizer.event_location(event),
            "updated_at": utc_now(),
        }
        event_update = {
            key: value
            for key, value in event_data.items()
            if value is not None
        }
        existing_event_id = (
            int(mapping["internal_id"])
            if mapping
            else self._find_existing_event(
                name,
                event_date,
                promotion_id,
            )
        )

        if dry_run:
            return {
                "status": "dry_run",
                "event_id": existing_event_id,
                "action": (
                    "update"
                    if existing_event_id is not None
                    else "insert"
                ),
            }

        event_id = existing_event_id
        result = save_entity(self.supabase, "event", event_update, self.source_id,
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
        gender = "Men"
        lowered = name.casefold()
        for prefix in ("women's ", "womens ", "women "):
            if lowered.startswith(prefix):
                gender = "Women"
                name = name[len(prefix):].strip()
                break
        for row in self._weight_classes():
            if (
                normalized_name(row["name"]) == normalized_name(name)
                and row["gender"].casefold() == gender.casefold()
            ):
                return int(row["weight_class_id"])
        return None

    def _find_existing_fight(
        self,
        event_id: int,
        fighter_a_id: int,
        fighter_b_id: int,
        fighter_a_name: str | None = None,
        fighter_b_name: str | None = None,
    ) -> int | None:
        response = (
            self.supabase.table("fights")
            .select(
                "fight_id, fighter_a_id, fighter_b_id, fight_status, "
                "fighter_a:fighters!fights_fighter_a_id_fkey(full_name), "
                "fighter_b:fighters!fights_fighter_b_id_fkey(full_name)"
            )
            .eq("event_id", event_id)
            .execute()
        )
        target_ids = tuple(sorted((fighter_a_id, fighter_b_id)))
        target_names = (
            tuple(sorted((
                fighter_name_key(fighter_a_name).replace(" ", ""),
                fighter_name_key(fighter_b_name).replace(" ", ""),
            )))
            if fighter_a_name and fighter_b_name
            else None
        )
        candidates: list[dict[str, Any]] = []
        for row in response.data or []:
            row_ids = tuple(sorted((
                int(row["fighter_a_id"]),
                int(row["fighter_b_id"]),
            )))
            id_match = row_ids == target_ids
            name_match = False
            if target_names:
                fighter_a = row.get("fighter_a") or {}
                fighter_b = row.get("fighter_b") or {}
                if isinstance(fighter_a, list):
                    fighter_a = fighter_a[0] if fighter_a else {}
                if isinstance(fighter_b, list):
                    fighter_b = fighter_b[0] if fighter_b else {}
                row_names = tuple(sorted((
                    fighter_name_key(
                        str(fighter_a.get("full_name") or "")
                    ).replace(" ", ""),
                    fighter_name_key(
                        str(fighter_b.get("full_name") or "")
                    ).replace(" ", ""),
                )))
                name_match = all(row_names) and row_names == target_names
            if id_match or name_match:
                candidates.append(row)

        if not candidates:
            return None
        if len(candidates) == 1:
            return int(candidates[0]["fight_id"])

        # When an earlier provider issue already created duplicates, preserve
        # the row carrying bets/research/odds. The lower ID is the stable tie
        # breaker because it is normally the original dashboard matchup.
        candidates.sort(
            key=lambda row: (
                -self._fight_usage_score(int(row["fight_id"])),
                int(row["fight_id"]),
            )
        )
        return int(candidates[0]["fight_id"])

    def _fight_usage_score(self, fight_id: int) -> int:
        score = 0
        try:
            research = (
                self.supabase.table("fight_research")
                .select(
                    "research_id, bet_side, user_lean, confidence, "
                    "assistant_pick, assistant_matchup_analysis"
                )
                .eq("fight_id", fight_id)
                .limit(1)
                .execute()
            )
            if research.data:
                score += 100
                row = research.data[0]
                if row.get("bet_side"):
                    score += 1000
                if any(row.get(field) not in (None, "", 0) for field in (
                    "user_lean",
                    "confidence",
                    "assistant_pick",
                    "assistant_matchup_analysis",
                )):
                    score += 400

            odds = (
                self.supabase.table("odds")
                .select("odds_id")
                .eq("fight_id", fight_id)
                .limit(1)
                .execute()
            )
            if odds.data:
                score += 200

            legs = (
                self.supabase.table("bet_legs")
                .select("leg_id")
                .eq("fight_id", fight_id)
                .limit(1)
                .execute()
            )
            if legs.data:
                score += 1200
        except Exception:
            # Selection must remain repair-safe if an older installation lacks
            # one optional table. Stable fight ID ordering remains the fallback.
            return score
        return score

    def import_fight(
        self,
        event_id: int,
        fight: dict[str, Any],
        fight_order: int,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        if normalizer.is_placeholder_fight(fight):
            return {
                "status": "skipped_placeholder",
                "fight_id": None,
                "fight_status": "scheduled",
            }

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
            "weight_class_id": self._weight_class_id(
                normalizer.weight_class(fight)
            ),
            "scheduled_rounds": normalizer.scheduled_rounds(fight),
            "fight_order": fight_order,
            "fight_status": fight_status,
            "is_title_fight": normalizer.is_title_fight(fight),
            "updated_at": utc_now(),
        }
        if fight_status in {"completed", "draw", "no_contest"}:
            fight_data.update(
                {
                    "winner_id": winner_id,
                    "result_type": normalizer.result_type(fight),
                    "method": normalizer.finish_method(fight),
                    "finish_round": normalizer.finish_round(fight),
                    "finish_time_seconds": normalizer.finish_time_seconds(fight),
                }
            )

        existing_fight_id = self._find_existing_fight(
            event_id,
            fighter_a_id,
            fighter_b_id,
            fighter_a["name"],
            fighter_b["name"],
        )

        fight_id = existing_fight_id or (int(mapping["internal_id"]) if mapping else None)
        if fight_id is not None:
            fight_data = preserve_fight_identity(self.supabase, fight_id, fight_data)
        result = save_entity(self.supabase, "fight", fight_data, self.source_id,
                             external_id, fight_id, fight.get("external_url"))
        return {"status": result["status"], "fight_id": int(result["internal_id"]),
                "fight_status": result["row"]["fight_status"]}


class PflImporter(EspnMmaImporter):
    def __init__(self, supabase_client: Any) -> None:
        super().__init__(
            supabase_client,
            promotion_aliases=PFL_ALIASES,
            promotion_label="PFL",
        )


class UfcImporter(EspnMmaImporter):
    def __init__(self, supabase_client: Any) -> None:
        super().__init__(
            supabase_client,
            promotion_aliases=UFC_ALIASES,
            promotion_label="UFC",
        )
        self.dwcs_promotion_id = self._get_promotion_id(DWCS_ALIASES)

    def _promotion_id_for_event(
        self,
        event: dict[str, Any],
    ) -> int:
        if normalizer.event_promotion_key(event) == "dwcs":
            return self.dwcs_promotion_id
        return self.promotion_id
