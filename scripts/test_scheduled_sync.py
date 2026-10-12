from datetime import datetime, timezone
import unittest
from scripts.scheduled_sync import due_slot, should_run, sync_arguments


class ScheduleTests(unittest.TestCase):
    def test_daily_uses_chicago_in_both_seasons(self):
        self.assertIsNone(
            due_slot("daily", datetime(2026, 7, 1, 12, 29, tzinfo=timezone.utc), 7, 30)
        )
        self.assertEqual(
            due_slot("daily", datetime(2026, 7, 1, 12, 30, tzinfo=timezone.utc), 7, 30),
            "2026-07-01",
        )
        self.assertIsNone(
            due_slot("daily", datetime(2026, 1, 1, 13, 29, tzinfo=timezone.utc), 7, 30)
        )
        self.assertEqual(
            due_slot("daily", datetime(2026, 1, 1, 13, 30, tzinfo=timezone.utc), 7, 30),
            "2026-01-01",
        )

    def test_catchup_and_retries_do_not_repeat_successful_slots(self):
        now = datetime(2026, 10, 12, 22, tzinfo=timezone.utc)
        self.assertEqual(should_run({}, "daily", now, 7, 30), "2026-10-12")
        self.assertIsNone(
            should_run({"successful_slot": "2026-10-12"}, "daily", now, 7, 30)
        )
        self.assertIsNone(
            should_run({"retry_at": "2026-10-12T23:00:00+00:00"}, "daily", now, 7, 30)
        )
        self.assertEqual(due_slot("history", now, 11, 0), "2026-10-11")

    def test_retries_refresh_cards_without_repeating_keyed_odds_calls(self):
        self.assertEqual(sync_arguments("daily", {}, "2026-10-12"), ["--mode", "daily"])
        self.assertIn(
            "--skip-keyed-odds",
            sync_arguments("daily", {"attempted_slot": "2026-10-12"}, "2026-10-12"),
        )
        self.assertNotIn(
            "--skip-keyed-odds",
            sync_arguments("daily", {"attempted_slot": "2026-10-11"}, "2026-10-12"),
        )

    def test_dst_fall_back_does_not_create_a_second_daily_run(self):
        now = datetime(2026, 11, 1, 14, tzinfo=timezone.utc)
        self.assertEqual(due_slot("daily", now, 7, 30), "2026-11-01")
        self.assertIsNone(
            should_run({"successful_slot": "2026-11-01"}, "daily", now, 7, 30)
        )
