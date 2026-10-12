from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from api.sync.freshness import EventFreshnessCache


class EventFreshnessCacheTests(unittest.TestCase):
    def test_fight_week_always_refreshes(self) -> None:
        now = datetime(2026, 10, 5, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            cache = EventFreshnessCache(Path(folder) / "state.json", now)
            listing = {"name": "Card", "date": "2026-10-10"}
            cache.mark("one", "card", listing)
            self.assertTrue(
                cache.should_refresh("one", "card", date(2026, 10, 10), listing)
            )

    def test_unchanged_distant_card_waits_three_days(self) -> None:
        first = datetime(2026, 10, 5, tzinfo=timezone.utc)
        listing = {"name": "Card", "date": "2026-10-20"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            cache = EventFreshnessCache(path, first)
            cache.mark("one", "card", listing)
            cache.save()
            next_day = EventFreshnessCache(path, first + timedelta(days=1))
            self.assertFalse(
                next_day.should_refresh("one", "card", date(2026, 10, 20), listing)
            )
            changed = {**listing, "name": "Card — updated"}
            self.assertTrue(
                next_day.should_refresh("one", "card", date(2026, 10, 20), changed)
            )


if __name__ == "__main__":
    unittest.main()
