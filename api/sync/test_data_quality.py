from __future__ import annotations

import unittest
from datetime import date, datetime, timezone, timedelta
from types import SimpleNamespace

from api.sync.data_quality import audit_upcoming_coverage


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, *_args):
        return self

    def gte(self, column, value):
        self.filters.append(lambda row: str(row.get(column, "")) >= str(value))
        return self

    def lte(self, column, value):
        self.filters.append(lambda row: str(row.get(column, "")) <= str(value))
        return self

    def in_(self, column, values):
        allowed = {str(value) for value in values}
        self.filters.append(lambda row: str(row.get(column)) in allowed)
        return self

    def execute(self):
        rows = [row for row in self.rows if all(check(row) for check in self.filters)]
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        return FakeQuery(self.rows.get(name, []))


class DataQualityTests(unittest.TestCase):
    def test_detects_partial_odds_and_unchecked_history(self):
        event_date = (date.today() + timedelta(days=2)).isoformat()
        client = FakeSupabase({
            "events": [{
                "event_id": 1,
                "event_name": "ONE Test",
                "event_date": event_date,
                "promotion_id": 4,
                "promotions": {"name": "ONE"},
            }],
            "fights": [
                {
                    "fight_id": 10, "event_id": 1, "fighter_a_id": 1,
                    "fighter_b_id": 2, "fight_status": "scheduled",
                    "fighter_a": {"full_name": "Alpha One"},
                    "fighter_b": {"full_name": "Beta Two"},
                },
                {
                    "fight_id": 11, "event_id": 1, "fighter_a_id": 3,
                    "fighter_b_id": 4, "fight_status": "scheduled",
                    "fighter_a": {"full_name": "Gamma Three"},
                    "fighter_b": {"full_name": "Delta Four"},
                },
            ],
            "mma_odds_observations": [{"fight_id":10,"fighter_id":fid,"sportsbook_key":"draftkings","american_odds":100,"observed_at":datetime.now(timezone.utc).isoformat()} for fid in (1,2)],
            "fighter_history_coverage": [
                {"fighter_id": 1, "coverage_status": "complete", "known_bout_count": 4},
                {"fighter_id": 2, "coverage_status": "complete", "known_bout_count": 3},
            ],
        })
        audit = audit_upcoming_coverage(client)
        codes = {issue["code"] for issue in audit["issues"]}
        self.assertIn("ODDS_CARD_PARTIAL", codes)
        self.assertIn("HISTORY_UNCHECKED", codes)
        self.assertEqual(audit["odds"]["covered_fights"], 1)
        self.assertEqual(audit["odds"]["expected_fights"], 2)
        self.assertEqual(audit["odds"]["expectation_window_days"], 4)
        odds_issue = next(issue for issue in audit["issues"] if issue["code"] == "ODDS_CARD_PARTIAL")
        self.assertEqual(
            odds_issue["missing_matchups"],
            [{"fight_id": 11, "matchup": "Gamma Three vs Delta Four"}],
        )

    def test_defers_missing_odds_outside_five_day_window(self):
        event_date = (date.today() + timedelta(days=6)).isoformat()
        client = FakeSupabase({
            "events": [{
                "event_id": 2,
                "event_name": "DWCS Next Week",
                "event_date": event_date,
                "promotion_id": 2,
                "promotions": {"name": "Dana White Contender Series"},
            }],
            "fights": [{
                "fight_id": 20, "event_id": 2, "fighter_a_id": 5,
                "fighter_b_id": 6, "fight_status": "scheduled",
                "fighter_a": {"full_name": "Future Alpha"},
                "fighter_b": {"full_name": "Future Beta"},
            }],
            "odds": [],
            "fighter_history_coverage": [
                {"fighter_id": 5, "coverage_status": "complete", "known_bout_count": 3},
                {"fighter_id": 6, "coverage_status": "confirmed_debut", "known_bout_count": 0},
            ],
        })
        audit = audit_upcoming_coverage(client)
        codes = {issue["code"] for issue in audit["issues"]}
        self.assertNotIn("ODDS_CARD_EMPTY", codes)
        self.assertNotIn("HISTORY_UNAVAILABLE", codes)
        self.assertEqual(audit["odds"]["expected_fights"], 0)
        self.assertEqual(audit["odds"]["deferred_cards"], 1)
        self.assertEqual(audit["history"]["confirmed_debuts"], 1)

    def test_defers_exact_five_day_boundary(self):
        event_date = (date.today() + timedelta(days=5)).isoformat()
        client = FakeSupabase({
            "events": [{
                "event_id": 22,
                "event_name": "DWCS Five Days Away",
                "event_date": event_date,
                "promotion_id": 2,
                "promotions": {"name": "Dana White Contender Series"},
            }],
            "fights": [{
                "fight_id": 220, "event_id": 22, "fighter_a_id": 51,
                "fighter_b_id": 52, "fight_status": "scheduled",
            }],
            "odds": [],
            "fighter_history_coverage": [],
        })

        audit = audit_upcoming_coverage(client)

        self.assertNotIn("ODDS_CARD_EMPTY", {row["code"] for row in audit["issues"]})
        self.assertEqual(audit["odds"]["expected_fights"], 0)

    def test_separates_partial_unavailable_and_review_history(self):
        event_date = (date.today() + timedelta(days=1)).isoformat()
        client = FakeSupabase({
            "events": [{
                "event_id": 3,
                "event_name": "LFA Tomorrow",
                "event_date": event_date,
                "promotion_id": 6,
                "promotions": {"name": "LFA"},
            }],
            "fights": [
                {"fight_id": 30, "event_id": 3, "fighter_a_id": 7, "fighter_b_id": 8, "fight_status": "scheduled"},
                {"fight_id": 31, "event_id": 3, "fighter_a_id": 9, "fighter_b_id": 10, "fight_status": "scheduled"},
            ],
            "odds": [{"fight_id": 30}, {"fight_id": 31}],
            "fighter_history_coverage": [
                {"fighter_id": 7, "coverage_status": "partial_history"},
                {"fighter_id": 8, "coverage_status": "history_unavailable"},
                {"fighter_id": 9, "coverage_status": "needs_review"},
                {"fighter_id": 10, "coverage_status": "confirmed_debut"},
            ],
        })
        audit = audit_upcoming_coverage(client)
        codes = {issue["code"] for issue in audit["issues"]}
        self.assertIn("HISTORY_PARTIAL", codes)
        self.assertIn("HISTORY_UNAVAILABLE", codes)
        self.assertIn("HISTORY_REVIEW", codes)
        self.assertNotIn("HISTORY_GAPS", codes)
        self.assertEqual(audit["history"]["unresolved"], 3)


if __name__ == "__main__":
    unittest.main()
