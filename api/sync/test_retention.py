from __future__ import annotations

import unittest
from datetime import date

from api.sync.retention import (
    apply_retention,
    preview_retention,
    retention_cutoff,
    run_retention,
)


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeRpc:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return FakeResponse(self.data)


class FakeSupabase:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return FakeRpc(self.responses[name])


class RetentionTests(unittest.TestCase):
    def test_cutoff_keeps_exactly_thirty_days(self):
        self.assertEqual(
            retention_cutoff(date(2026, 8, 10), 30),
            date(2026, 7, 11),
        )

    def test_preview_reports_candidates_without_apply_call(self):
        client = FakeSupabase({
            "preview_mma_retention": [
                {"event_id": 1, "fight_count": 10},
                {"event_id": 2, "fight_count": 7},
            ]
        })
        result = preview_retention(client, 30)
        self.assertEqual(result["events_eligible"], 2)
        self.assertEqual(result["fights_eligible"], 17)
        self.assertEqual(
            client.calls,
            [("preview_mma_retention", {"keep_days": 30})],
        )

    def test_apply_returns_atomic_database_counts(self):
        client = FakeSupabase({
            "apply_mma_retention": [{
                "cutoff_date": "2026-07-11",
                "events_deleted": 3,
                "fights_deleted": 28,
            }]
        })
        result = apply_retention(client, 30)
        self.assertEqual(result["events_deleted"], 3)
        self.assertEqual(result["fights_deleted"], 28)

    def test_skipped_retention_makes_no_rpc_call(self):
        client = FakeSupabase({})
        result = run_retention(client, skipped=True)
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
