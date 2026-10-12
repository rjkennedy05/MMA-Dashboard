from __future__ import annotations

import unittest

from matching import (
    matching_event_id,
    matching_fight_id,
    matching_fighter_id,
    normalized_name,
    parse_height_inches,
    parse_reach_inches,
)


class MatchingTests(unittest.TestCase):
    def test_names_match_with_or_without_diacritics(self) -> None:
        self.assertEqual(normalized_name("Uroš Medić"), "uros medic")
        self.assertEqual(normalized_name("Uros Medic"), "uros medic")

    def test_real_event_wins_over_same_date_test_event(self) -> None:
        rows = [
            {"event_id": 1, "event_name": "UFC Test Event"},
            {
                "event_id": 2,
                "event_name": "UFC Fight Night: Medic vs. Rodriguez",
            },
        ]
        self.assertEqual(
            matching_event_id(
                rows,
                "UFC Fight Night: Medić vs. Rodriguez",
            ),
            2,
        )

    def test_existing_fighter_and_reversed_matchup_are_reused(self) -> None:
        fighter_rows = [
            {"fighter_id": 10, "full_name": "Uros Medic"},
        ]
        fight_rows = [
            {
                "fight_id": 20,
                "fighter_a_id": 11,
                "fighter_b_id": 10,
            },
        ]
        self.assertEqual(
            matching_fighter_id(fighter_rows, "Uroš Medić"),
            10,
        )
        self.assertEqual(matching_fight_id(fight_rows, 10, 11), 20)

    def test_missing_profile_measurements_do_not_abort_fight_import(self) -> None:
        self.assertIsNone(parse_height_inches("--"))
        self.assertIsNone(parse_reach_inches("--"))
        self.assertIsNone(parse_height_inches(None))
        self.assertEqual(parse_height_inches("6' 2\""), 74)
        self.assertEqual(parse_reach_inches('76"'), 76)


if __name__ == "__main__":
    unittest.main()
