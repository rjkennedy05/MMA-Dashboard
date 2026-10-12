import unittest
from datetime import date

try:
    from .normalizer import (
        decimal_to_american,
        names_compatible,
        normalize_history,
        normalize_odds_fight,
        partition_dates_for_plan,
    )
except ImportError:
    from normalizer import (
        decimal_to_american,
        names_compatible,
        normalize_history,
        normalize_odds_fight,
        partition_dates_for_plan,
    )


class ApiSportsNormalizerTests(unittest.TestCase):
    def test_decimal_to_american(self):
        self.assertEqual(decimal_to_american("2.50"), 150)
        self.assertEqual(decimal_to_american("1.50"), -200)

    def test_names_accept_suffix_and_quoted_nickname_differences(self):
        self.assertTrue(names_compatible("Michael Aswell Jr.", "Michael Aswell"))
        self.assertTrue(names_compatible('Jane "The Hammer" Doe', "Jane Doe"))
        self.assertFalse(names_compatible("Jane Doe", "Janet Doe"))

    def test_free_plan_dates_only_query_today_and_tomorrow(self):
        eligible, deferred = partition_dates_for_plan(
            ["2026-09-17", "2026-09-18", "2026-09-19", "2026-09-22"],
            date(2026, 9, 17),
        )
        self.assertEqual(eligible, ["2026-09-17", "2026-09-18"])
        self.assertEqual(deferred, ["2026-09-19", "2026-09-22"])

    def test_normalizes_winner_market(self):
        row = {
            "fight": {"id": 42, "date": "2026-09-20T23:00:00+00:00"},
            "fighters": {
                "first": {"id": 1, "name": "Jane Doe"},
                "second": {"id": 2, "name": "Mary Roe"},
            },
            "bookmakers": [{
                "id": 8,
                "name": "Example Book",
                "bets": [{
                    "name": "Winner",
                    "values": [
                        {"value": "Jane Doe", "odd": "1.80"},
                        {"value": "Mary Roe", "odd": "2.10"},
                    ],
                }],
            }],
        }
        normalized = normalize_odds_fight(row)
        self.assertEqual(normalized["home_team"], "Jane Doe")
        self.assertEqual(normalized["bookmakers"][0]["markets"][0]["outcomes"][0]["price"], -125)

    def test_normalizes_fighters_nested_inside_fight(self):
        row = {
            "fight": {
                "id": 43,
                "date": "2026-09-20T23:00:00+00:00",
                "fighters": {
                    "first": {"id": 1, "name": "Nested Jane"},
                    "second": {"id": 2, "name": "Nested Mary"},
                },
            },
            "bookmakers": [{
                "id": 8,
                "name": "Example Book",
                "bets": [{
                    "name": "Winner",
                    "values": [
                        {"value": "Nested Jane", "odd": "1.75"},
                        {"value": "Nested Mary", "odd": "2.15"},
                    ],
                }],
            }],
        }
        normalized = normalize_odds_fight(row)
        self.assertEqual(normalized["home_team"], "Nested Jane")
        self.assertEqual(normalized["away_team"], "Nested Mary")

    def test_uses_winner_market_names_when_fighter_objects_are_absent(self):
        row = {
            "fight": {"id": 44, "date": "2026-09-20T23:00:00+00:00"},
            "bookmakers": [{
                "id": 8,
                "name": "Example Book",
                "bets": [{
                    "name": "Winner",
                    "values": [
                        {"value": "Market Jane", "odd": "1.65"},
                        {"value": "Market Mary", "odd": "2.30"},
                    ],
                }],
            }],
        }
        normalized = normalize_odds_fight(row)
        self.assertEqual(normalized["home_team"], "Market Jane")
        self.assertEqual(normalized["away_team"], "Market Mary")

    def test_normalizes_fighter_history(self):
        fighter = {"id": 1, "name": "Jane Doe"}
        rows = [{
            "fight": {"id": 99, "date": "2026-01-02", "status": "Finished"},
            "fighters": {
                "first": fighter,
                "second": {"id": 2, "name": "Mary Roe", "record": "8-3-0"},
            },
            "results": {"winner": 1, "method": "Submission", "round": 2, "time": "3:14"},
            "league": {"name": "LFA"},
        }]
        history = normalize_history(rows, fighter)
        self.assertEqual(history[0]["outcome"], "W")
        self.assertEqual(history[0]["opponent_name"], "Mary Roe")
        self.assertEqual(history[0]["finish_time_seconds"], 194)


if __name__ == "__main__":
    unittest.main()
