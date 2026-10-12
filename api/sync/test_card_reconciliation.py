from __future__ import annotations

import unittest

from api.sync.card_reconciliation import missing_scheduled_fight_ids


class CardReconciliationTests(unittest.TestCase):
    def test_archives_only_missing_scheduled_rows(self) -> None:
        rows = [
            {"fight_id": 10, "fight_status": "scheduled"},
            {"fight_id": 11, "fight_status": "upcoming"},
            {"fight_id": 12, "fight_status": "completed"},
            {"fight_id": 13, "fight_status": "cancelled"},
        ]
        self.assertEqual(missing_scheduled_fight_ids(rows, [11]), [10])

    def test_empty_provider_card_never_archives_existing_rows(self) -> None:
        rows = [{"fight_id": 10, "fight_status": "scheduled"}]
        self.assertEqual(missing_scheduled_fight_ids(rows, []), [])

    def test_reordered_current_fights_remain_active(self) -> None:
        rows = [
            {"fight_id": 10, "fight_status": "scheduled"},
            {"fight_id": 11, "fight_status": "scheduled"},
        ]
        self.assertEqual(missing_scheduled_fight_ids(rows, [11, 10]), [])


if __name__ == "__main__":
    unittest.main()
