from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parent / "fight_matcher.py"


def load_matcher_module():
    fake_uploader = types.ModuleType("uploader")
    fake_uploader.supabase = object()
    previous_uploader = sys.modules.get("uploader")
    sys.modules["uploader"] = fake_uploader
    try:
        spec = importlib.util.spec_from_file_location("tested_fight_matcher", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        if previous_uploader is None:
            sys.modules.pop("uploader", None)
        else:
            sys.modules["uploader"] = previous_uploader


class FightMatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.matcher = load_matcher_module()

    def test_matches_generational_suffix_difference(self) -> None:
        api_fight = {
            "home_team": "Joo Sang Yoo",
            "away_team": "Michael Aswell",
            "commence_time": "2026-09-20T00:00:00Z",
        }
        database_fights = [{
            "fight_id": 331,
            "fighter_a": {"fighter_id": 1, "full_name": "Michael Aswell Jr."},
            "fighter_b": {"fighter_id": 2, "full_name": "Joo Sang Yoo"},
            "events": {"event_date": "2026-09-19"},
        }]

        match = self.matcher.match_api_fight(api_fight, database_fights)

        self.assertEqual(match["status"], "matched")
        self.assertEqual(match["fight"]["fight_id"], 331)
        self.assertEqual(
            self.matcher.get_fighter_id_for_selection(
                database_fights[0], "Michael Aswell"
            ),
            1,
        )

    def test_matches_compacted_given_name_spacing(self) -> None:
        api_fight = {
            "home_team": "Joo Sang Yoo",
            "away_team": "Michael Aswell",
            "commence_time": "2026-09-20T00:00:00Z",
        }
        database_fights = [{
            "fight_id": 437,
            "fighter_a": {"fighter_id": 8, "full_name": "Michael Aswell"},
            "fighter_b": {"fighter_id": 9, "full_name": "JooSang Yoo"},
            "events": {"event_date": "2026-09-19"},
        }]

        match = self.matcher.match_api_fight(api_fight, database_fights)

        self.assertEqual(match["status"], "matched")
        self.assertEqual(match["fight"]["fight_id"], 437)
        self.assertEqual(
            self.matcher.get_fighter_id_for_selection(
                database_fights[0], "Joo Sang Yoo"
            ),
            9,
        )

    def test_explains_name_match_outside_date_tolerance(self) -> None:
        api_fight = {
            "home_team": "Alpha One",
            "away_team": "Beta Two",
            "commence_time": "2026-09-20T00:00:00Z",
        }
        database_fights = [{
            "fight_id": 44,
            "fighter_a": {"fighter_id": 1, "full_name": "Alpha One"},
            "fighter_b": {"fighter_id": 2, "full_name": "Beta Two"},
            "events": {"event_date": "2026-09-16"},
        }]

        match = self.matcher.match_api_fight(api_fight, database_fights)

        self.assertEqual(match["status"], "unmatched")
        self.assertEqual(match["name_match_fight_id"], 44)
        self.assertIn("3 days away", match["reason"])


if __name__ == "__main__":
    unittest.main()
