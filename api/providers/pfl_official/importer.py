"""Reuse the shared identity/transaction importer with official PFL provenance."""

from ..espn_mma import normalizer
from ..espn_mma.importer import PflImporter, fighter_name_key, utc_now
from ..event_catalog.importer import SOURCE_NAMES
from ..fight_identity import FightIdentityError
from ..persistence import save_entity


class OfficialPflImporter(PflImporter):
    def _link_saved_matchup_fighters(self, event_id, fight):
        """Use both opponents on this card before global fighter-name lookup.

        Historical imports can contain two fighter rows whose names normalize
        identically. Creating another fighter in that case makes the existing
        fight fail the identity guard. The saved event matchup supplies context
        for the first official-source attachment; established mappings still
        take precedence and must agree. No fighter or fight records are merged.
        """
        incoming = normalizer.fighters(fight)
        names = tuple(fighter_name_key(f["name"]).replace(" ", "") for f in incoming)
        if not all(names) or names[0] == names[1]:
            raise FightIdentityError("The PFL matchup needs two distinct fighter identities.")
        rows = (self.supabase.table("fights").select(
            "fight_id, fighter_a_id, fighter_b_id, fight_status, "
            "fighter_a:fighters!fights_fighter_a_id_fkey(full_name), "
            "fighter_b:fighters!fights_fighter_b_id_fkey(full_name)"
        ).eq("event_id", event_id).execute().data or [])
        pairs = set()
        matched_fights = set()
        for row in rows:
            sides = []
            for side in ("fighter_a", "fighter_b"):
                fighter = row.get(side) or {}
                if isinstance(fighter, list):
                    fighter = fighter[0] if fighter else {}
                sides.append((fighter_name_key(str(fighter.get("full_name") or "")).replace(" ", ""),
                              int(row[side + "_id"])))
            for ordered in (sides, sides[::-1]):
                if tuple(side[0] for side in ordered) == names:
                    pairs.add(tuple(side[1] for side in ordered))
                    matched_fights.add(int(row["fight_id"]))
        if not pairs:
            return  # A new matchup uses the normal provider identity path.
        if len(pairs) != 1:
            raise FightIdentityError(
                "The PFL matchup matches multiple saved fighter pairs. "
                "Existing bets and research were preserved; review the duplicate records."
            )
        fight_mapping = self._external_mapping("fight", normalizer.fight_external_id(fight))
        if fight_mapping and int(fight_mapping["internal_id"]) not in matched_fights:
            raise FightIdentityError(
                "The PFL fight source ID points to another saved matchup. "
                "Existing bets and research were preserved; review the source mapping."
            )
        saved_ids = next(iter(pairs))
        mappings = [self._external_mapping("fighter", f["external_id"]) for f in incoming]
        # Check both identities before attaching either, including callers that
        # import one fight outside the whole-card transaction.
        for fighter, fighter_id, mapping in zip(incoming, saved_ids, mappings):
            if mapping and int(mapping["internal_id"]) != fighter_id:
                raise FightIdentityError(
                    f"PFL fighter {fighter['name']} maps to #{mapping['internal_id']}, "
                    f"but this saved matchup uses #{fighter_id}. Existing bets and "
                    "research were preserved; review the fighter source mapping."
                )
        for fighter, fighter_id, mapping in zip(incoming, saved_ids, mappings):
            if not mapping:
                self._attach_mapping("fighter", fighter_id, fighter["external_id"],
                                     fighter.get("external_url"))

    def import_fight(self, event_id, fight, fight_order, dry_run=False):
        if not dry_run and not normalizer.is_placeholder_fight(fight):
            self._link_saved_matchup_fighters(event_id, fight)
        return super().import_fight(event_id, fight, fight_order, dry_run=dry_run)

    def _get_source_id(self):
        rows = (self.supabase.table("data_sources").select("source_id")
                .eq("name", SOURCE_NAMES["pfl"]).limit(1).execute().data or [])
        if len(rows) != 1:
            raise RuntimeError("The existing official PFL catalog source is missing. Verify migration 030.")
        return int(rows[0]["source_id"])

    def import_event(self, event, dry_run=False):
        mapping = self._external_mapping("event", event["external_id"])
        event_id = (int(mapping["internal_id"]) if mapping else
                    self._find_existing_event(event["name"], event["event_date"], self.promotion_id))
        if dry_run:
            return {"status": "dry_run", "event_id": event_id}
        payload = {"promotion_id": self.promotion_id, "event_name": event["name"],
                   "event_date": event["event_date"], "updated_at": utc_now()}
        payload.update({k: event[k] for k in ("event_status", "event_start_time", "venue", "city", "country")
                        if event.get(k) is not None})
        saved = save_entity(self.supabase, "event", payload, self.source_id,
                            event["external_id"], event_id, event["external_url"])
        return {"status": saved["status"], "event_id": int(saved["internal_id"])}
