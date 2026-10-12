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
        if name!="mma_record_odds":raise AssertionError(name)
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
        database_fight = {"fight_id": 9}

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


if __name__ == "__main__":
    unittest.main()
