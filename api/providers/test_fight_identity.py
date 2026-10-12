from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from api.providers.bkfc.importer import BkfcImporter
from api.providers.espn_mma.importer import PflImporter, UfcImporter
from api.providers.fight_identity import FightIdentityError, preserve_fight_identity
from api.providers.lfa.importer import LfaImporter
from api.providers.one_championship.importer import OneChampionshipImporter
from api.ufcstats import matching


class MemoryQuery:
    def __init__(self, database, table):
        self.database, self.table_name = database, table
        self.filters, self.operation, self.payload = [], "select", None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _count):
        return self

    def update(self, payload):
        self.operation, self.payload = "update", deepcopy(payload)
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", deepcopy(payload)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def execute(self):
        rows = self.database.rows[self.table_name]
        matches = [row for row in rows if all(row.get(k) == v for k, v in self.filters)]
        if self.operation == "insert":
            key = {"fights": "fight_id", "external_ids": "external_id_map_id"}[self.table_name]
            row = {key: max((int(r[key]) for r in rows), default=0) + 1, **self.payload}
            rows.append(row)
            matches = [row]
        elif self.operation == "update":
            for row in matches:
                row.update(self.payload)
        elif self.operation == "delete":
            rows[:] = [row for row in rows if row not in matches]
        return SimpleNamespace(data=deepcopy(matches))


class MemoryDatabase:
    def __init__(self, mapped=True):
        self.rows = {
            "fights": [{
                "fight_id": 100, "event_id": 5, "fighter_a_id": 11, "fighter_b_id": 12,
                "fight_status": "scheduled", "fight_order": 1,
                "fighter_a": {"full_name": "Fighter A"},
                "fighter_b": {"full_name": "Fighter B"},
            }],
            "external_ids": [{
                "external_id_map_id": 1, "entity_type": "fight", "source_id": 7,
                "internal_id": 100, "external_id": "source100",
            }] if mapped else [],
            "fight_research": [{
                "fight_id": 100, "bet_side": "fighter_a", "bet_price": -120,
                "stake_units": 1, "user_lean": "fighter_b", "assistant_pick": "fighter_a",
            }],
            "bet_legs": [{"leg_id": 1, "fight_id": 100, "bet_side": "fighter_b", "leg_price": 110}],
            "odds": [],
        }

    def table(self, name):
        return MemoryQuery(self, name)


def provider_fight(importer_type, replacement=False):
    first_id, first_name = (13, "Replacement") if replacement else (12, "Fighter B")
    if importer_type in (UfcImporter, PflImporter):
        return {
            "id": "source100",
            "competitors": [
                {"order": 1, "winner": True, "athlete": {"id": str(first_id), "displayName": first_name}},
                {"order": 2, "winner": False, "athlete": {"id": "11", "displayName": "Fighter A"}},
            ],
            "status": {"type": {"completed": True, "state": "post"},
                       "result": {"displayName": "KO"}, "period": 2, "clock": 61},
        }
    return {
        "external_id": "source100",
        "fighter_a": {"external_id": str(first_id), "name": first_name, "winner": True},
        "fighter_b": {"external_id": "11", "name": "Fighter A", "winner": False},
        "fight_status": "completed", "result_type": "win", "method": "KO",
        "finish_round": 2, "finish_time_seconds": 61, "ruleset": "MMA",
    }


IMPORTERS = (UfcImporter, PflImporter, OneChampionshipImporter, LfaImporter, BkfcImporter)


def make_importer(importer_type, database):
    importer = importer_type.__new__(importer_type)
    importer.supabase, importer.source_id, importer.promotion_label = database, 7, "Test promotion"
    importer.get_or_create_fighter = lambda fighter: int(fighter["external_id"])
    importer._weight_class_id = lambda _name: None
    return importer


class FightIdentityTests(unittest.TestCase):
    def test_reversal_preserves_sides_without_mutating_input_or_winner(self):
        database = MemoryDatabase()
        payload = {"event_id": 5, "fighter_a_id": 12, "fighter_b_id": 11, "winner_id": 12}
        updated = preserve_fight_identity(database, 100, payload)
        self.assertEqual((updated["fighter_a_id"], updated["fighter_b_id"]), (11, 12))
        self.assertEqual(updated["winner_id"], 12)
        self.assertEqual(payload["fighter_a_id"], 12)

    def test_mapped_updates_keep_single_and_parlay_selections_after_repeated_import(self):
        for importer_type in IMPORTERS:
            with self.subTest(provider=importer_type.__name__):
                database = MemoryDatabase()
                bets = deepcopy((database.rows["fight_research"], database.rows["bet_legs"]))
                importer = make_importer(importer_type, database)
                for _ in range(2):
                    result = importer.import_fight(5, provider_fight(importer_type), 3)
                    self.assertEqual(result["fight_id"], 100)
                stored = database.rows["fights"][0]
                self.assertEqual((stored["fighter_a_id"], stored["fighter_b_id"]), (11, 12))
                self.assertEqual(stored["winner_id"], 12)
                self.assertEqual(stored["fight_order"], 3)
                self.assertEqual(stored["fight_status"], "completed")
                self.assertEqual((database.rows["fight_research"], database.rows["bet_legs"]), bets)
                self.assertEqual(len(database.rows["fights"]), 1)
                self.assertEqual(len(database.rows["external_ids"]), 1)

    def test_first_provider_attachment_preserves_stored_orientation(self):
        for importer_type in IMPORTERS:
            with self.subTest(provider=importer_type.__name__):
                database = MemoryDatabase(mapped=False)
                result = make_importer(importer_type, database).import_fight(5, provider_fight(importer_type), 3)
                self.assertEqual(result["fight_id"], 100)
                self.assertEqual(database.rows["fights"][0]["fighter_a_id"], 11)
                self.assertEqual(database.rows["external_ids"][0]["internal_id"], 100)

    def test_changed_opponent_is_refused_without_modifying_fight_bets_or_mapping(self):
        for importer_type in IMPORTERS:
            with self.subTest(provider=importer_type.__name__):
                database = MemoryDatabase()
                before = deepcopy(database.rows)
                with self.assertRaisesRegex(FightIdentityError, "different stored participants"):
                    make_importer(importer_type, database).import_fight(5, provider_fight(importer_type, replacement=True), 3)
                self.assertEqual(database.rows, before)

    def test_rebooking_cannot_move_the_original_ticket_to_another_event(self):
        for importer_type in IMPORTERS:
            with self.subTest(provider=importer_type.__name__):
                database = MemoryDatabase()
                before = deepcopy(database.rows)
                with self.assertRaisesRegex(FightIdentityError, "another event"):
                    make_importer(importer_type, database).import_fight(6, provider_fight(importer_type), 3)
                self.assertEqual(database.rows, before)

    def test_new_fights_keep_provider_order(self):
        for importer_type in IMPORTERS:
            with self.subTest(provider=importer_type.__name__):
                database = MemoryDatabase(mapped=False)
                database.rows["fights"] = []
                result = make_importer(importer_type, database).import_fight(5, provider_fight(importer_type), 3)
                self.assertEqual(result["status"], "imported")
                self.assertEqual(database.rows["fights"][0]["fighter_a_id"], 12)

    def test_missing_mapped_row_is_refused(self):
        database = MemoryDatabase()
        database.rows["fights"] = []
        with self.assertRaisesRegex(FightIdentityError, "not found"):
            preserve_fight_identity(database, 100, {"event_id": 5, "fighter_a_id": 11, "fighter_b_id": 12})

    def test_guard_precedes_espn_mapping_removal_for_name_matched_duplicates(self):
        database = MemoryDatabase()
        database.rows["fights"].append({
            **database.rows["fights"][0], "fight_id": 99, "fighter_a_id": 21, "fighter_b_id": 22,
        })
        database.rows["fight_research"].append({"fight_id": 99, "bet_side": "fighter_a", "assistant_pick": "fighter_a"})
        importer = make_importer(UfcImporter, database)
        importer._find_existing_fight = lambda *_args: 99
        before = deepcopy(database.rows)
        with self.assertRaises(FightIdentityError):
            importer.import_fight(5, provider_fight(UfcImporter), 3)
        self.assertEqual(database.rows, before)


def load_ufcstats_importer(database):
    # The legacy uploader initializes authentication at import time. Substitute
    # only that connection and unused scrapers; run the real import_fight code.
    uploader = ModuleType("uploader")
    uploader.supabase = database
    fighter_importer = ModuleType("fighter_importer")
    fighter_importer.import_fighter = lambda *_args: (_ for _ in ()).throw(AssertionError("Unexpected scrape"))
    detail_scraper = ModuleType("fight_detail_scraper")
    detail_scraper.scrape_fight_detail = fighter_importer.import_fighter
    path = Path(__file__).resolve().parents[1] / "ufcstats" / "fight_importer.py"
    spec = importlib.util.spec_from_file_location("identity_test_ufcstats_importer", path)
    module = importlib.util.module_from_spec(spec)
    saved_path = sys.path[:]
    try:
        with patch.dict(sys.modules, {
            "uploader": uploader, "fighter_importer": fighter_importer,
            "fight_detail_scraper": detail_scraper, "matching": matching,
        }):
            spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved_path
    return module


class UfcstatsFightIdentityTests(unittest.TestCase):
    def run_import(self, database, event_id=5, first_id=12):
        module = load_ufcstats_importer(database)
        module.get_event_id = lambda _url: event_id
        module.build_fight_data = lambda *_args: {
            "event_id": event_id, "fighter_a_id": first_id, "fighter_b_id": 11,
            "winner_id": first_id, "fight_status": "completed", "fight_order": 3,
        }
        for mapping in database.rows["external_ids"]:
            mapping["source_id"] = 1
        return module.import_fight("https://example.test/event", {
            "fight_url": "https://example.test/source100", "fighter_a_name": "Fighter B", "fighter_b_name": "Fighter A",
        }, detail={"fight_status": "completed"})

    def test_mapped_completed_import_keeps_original_sides_and_winner(self):
        database = MemoryDatabase()
        self.run_import(database)
        self.assertEqual(database.rows["fights"][0]["fighter_a_id"], 11)
        self.assertEqual(database.rows["fights"][0]["winner_id"], 12)

    def test_unmapped_attachment_preserves_original_sides(self):
        database = MemoryDatabase(mapped=False)
        self.run_import(database)
        self.assertEqual(database.rows["fights"][0]["fighter_a_id"], 11)
        self.assertEqual(database.rows["external_ids"][0]["internal_id"], 100)

    def test_replacement_is_refused(self):
        database = MemoryDatabase()
        with self.assertRaisesRegex(RuntimeError, "different stored participants"):
            self.run_import(database, first_id=13)
        self.assertEqual(database.rows["fights"][0]["fighter_b_id"], 12)

    def test_rebooking_is_refused(self):
        database = MemoryDatabase()
        with self.assertRaisesRegex(RuntimeError, "another event"):
            self.run_import(database, event_id=6)
        self.assertEqual(database.rows["fights"][0]["event_id"], 5)


if __name__ == "__main__":
    unittest.main()
