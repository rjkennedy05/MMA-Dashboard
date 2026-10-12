from __future__ import annotations

import unittest
from datetime import date

from api.sync.incremental import (
    should_process_ufcstats_event,
    ufcstats_refresh_reason,
)


class IncrementalUfcstatsTests(unittest.TestCase):
    def test_future_events_are_not_scraped_for_enrichment(self) -> None:
        self.assertFalse(
            should_process_ufcstats_event(date(2026, 8, 11), date(2026, 8, 10))
        )
        self.assertTrue(
            should_process_ufcstats_event(date(2026, 8, 10), date(2026, 8, 10))
        )

    def test_old_completed_mapped_fight_is_skipped(self) -> None:
        reason = ufcstats_refresh_reason(
            fight_external_id="fight-1",
            event_date=date(2026, 8, 1),
            today=date(2026, 8, 10),
            mapped_fights={"fight-1": 41},
            fight_statuses={41: "completed"},
            refresh_days=1,
            full_repair=False,
        )
        self.assertIsNone(reason)

    def test_missing_mapping_or_result_is_repaired(self) -> None:
        base = {
            "fight_external_id": "fight-1",
            "event_date": date(2026, 8, 1),
            "today": date(2026, 8, 10),
            "refresh_days": 1,
            "full_repair": False,
        }
        self.assertEqual(
            ufcstats_refresh_reason(
                **base,
                mapped_fights={},
                fight_statuses={},
            ),
            "missing_mapping",
        )
        self.assertEqual(
            ufcstats_refresh_reason(
                **base,
                mapped_fights={"fight-1": 41},
                fight_statuses={41: "scheduled"},
            ),
            "missing_result",
        )

    def test_recent_and_full_repair_modes_refresh_completed_fights(self) -> None:
        common = {
            "fight_external_id": "fight-1",
            "today": date(2026, 8, 10),
            "mapped_fights": {"fight-1": 41},
            "fight_statuses": {41: "completed"},
            "refresh_days": 1,
        }
        self.assertEqual(
            ufcstats_refresh_reason(
                **common,
                event_date=date(2026, 8, 9),
                full_repair=False,
            ),
            "recent_result_check",
        )
        self.assertEqual(
            ufcstats_refresh_reason(
                **common,
                event_date=date(2026, 8, 1),
                full_repair=True,
            ),
            "full_repair",
        )


if __name__ == "__main__":
    unittest.main()
