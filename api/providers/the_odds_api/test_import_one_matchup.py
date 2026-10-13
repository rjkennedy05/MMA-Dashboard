from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path


PROVIDER_ROOT = Path(__file__).resolve().parent


class FakeQuery:
    def __init__(self, database: "FakeSupabase") -> None:
        self.database = database
        self.inserted_rows = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def insert(self, rows):
        self.inserted_rows = rows
        return self

    def execute(self):
        if self.inserted_rows is not None:
            self.database.inserted.extend(self.inserted_rows)
            return types.SimpleNamespace(data=self.inserted_rows)

        return types.SimpleNamespace(data=[])


class FakeSupabase:
    def __init__(self) -> None:
        self.inserted = []

    def rpc(self,name,args):
        if name!="mma_record_odds_resilient":raise AssertionError(name)
        def execute():
            self.inserted.extend(args["p_rows"])
            return types.SimpleNamespace(data={"inserted":len(args["p_rows"]),"unchanged":0,"skipped":0})
        return types.SimpleNamespace(execute=execute)

    def table(self, _name):
        return FakeQuery(self)


class ImportOneMatchupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(PROVIDER_ROOT))
        cls.database = FakeSupabase()

        fake_client = types.ModuleType("client")
        fake_client.get_current_mma_moneylines = lambda: ([], {})
        fake_client.supabase = cls.database
        sys.modules["client"] = fake_client

        fake_matcher = types.ModuleType("fight_matcher")
        fake_matcher.load_database_fights = lambda: []
        fake_matcher.match_api_fight = lambda *_args: {}
        fake_matcher.matchup_key = lambda *names: tuple(sorted(names))
        fake_matcher.get_fighter_id_for_selection = (
            lambda _fight, selection: {"Fighter A": 11, "Fighter B": 12}.get(
                selection
            )
        )
        sys.modules["fight_matcher"] = fake_matcher

        cls.module = importlib.import_module("import_one_matchup")

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path.remove(str(PROVIDER_ROOT))
        for name in ("import_one_matchup", "client", "fight_matcher"):
            sys.modules.pop(name, None)

    def setUp(self) -> None:
        self.database.inserted.clear()

    def test_snapshot_keeps_stable_book_key_and_bout_start(self) -> None:
        api_fight = {
            "commence_time": "2026-08-12T01:00:00Z",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": "2026-08-10T18:00:00Z",
                            "outcomes": [
                                {"name": "Fighter A", "price": -130},
                                {"name": "Fighter B", "price": 110},
                            ],
                        }
                    ],
                }
            ],
        }
        database_fight = {"fight_id": 9, "fighter_a": {"fighter_id": 11, "full_name": "Fighter A"},
                          "fighter_b": {"fighter_id": 12, "full_name": "Fighter B"}}

        result = self.module.import_moneylines(
            api_fight,
            database_fight,
            source_id=2,
        )

        self.assertEqual(result["inserted"], 2)
        self.assertEqual(self.database.inserted[0]["sportsbook_key"], "draftkings")
        self.assertEqual(
            self.database.inserted[0]["market_commence_time"],
            "2026-08-12T01:00:00Z",
        )

    def test_invalid_or_missing_quote_rejects_that_book_but_keeps_the_other_pair(self):
        database_fight = {"fight_id": 9, "fighter_a": {"full_name": "Fighter A"},
                          "fighter_b": {"full_name": "Fighter B"}}
        for invalid in (0, "bad", float("nan"), 1.5, None):
            with self.subTest(price=invalid):
                self.database.inserted.clear()
                def book(key, outcomes):
                    return {"key": key, "title": key, "markets": [{"key": "h2h", "outcomes": outcomes}]}
                result = self.module.import_moneylines({"bookmakers": [
                    book("bad", [{"name": "Fighter A", "price": -110}, {"name": "Fighter B", "price": invalid}]),
                    book("good", [{"name": "Fighter A", "price": -130}, {"name": "Fighter B", "price": 110}])]},
                    database_fight, 2)
                self.assertEqual(result["inserted"], 2)
                self.assertEqual(len(result["errors"]), 1)
                self.assertEqual({row["sportsbook_key"] for row in self.database.inserted}, {"good"})

    def test_one_sided_and_duplicate_outcomes_never_refresh_a_partial_pair(self):
        fight = {"fight_id": 9, "fighter_a": {"full_name": "Fighter A"}, "fighter_b": {"full_name": "Fighter B"}}
        for names in ([], ["Fighter A"], ["Fighter A", "Fighter A"], ["Fighter A", "Fighter B", "Fighter A"]):
            with self.subTest(names=names):
                result = self.module.import_moneylines({"bookmakers": [{"key": "bad", "title": "Bad", "markets": [
                    {"key": "h2h", "outcomes": [{"name": name, "price": 110} for name in names]}]}]}, fight, 2)
                self.assertEqual(result["inserted"], 0)
                self.assertEqual(len(result["errors"]), 1)
                self.assertEqual(self.database.inserted, [])


if __name__ == "__main__":
    unittest.main()
