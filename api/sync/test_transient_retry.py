from __future__ import annotations

import unittest

from .transient_retry import (
    is_transient_connection_error,
    run_with_transient_retry,
)


class TransientRetryTests(unittest.TestCase):
    def test_connection_terminated_is_transient(self) -> None:
        error = RuntimeError(
            "<ConnectionTerminated error_code:0, last_stream_id:19999>"
        )
        self.assertTrue(is_transient_connection_error(error))

    def test_business_error_is_not_retried(self) -> None:
        calls = 0

        def operation():
            nonlocal calls
            calls += 1
            raise RuntimeError("duplicate key value violates constraint")

        with self.assertRaisesRegex(RuntimeError, "duplicate key"):
            run_with_transient_retry(operation, label="fight", sleeper=lambda _: None)
        self.assertEqual(calls, 1)

    def test_transient_operation_retries_and_recovers(self) -> None:
        calls = 0
        retries: list[int] = []

        def operation():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise RuntimeError("ConnectionTerminated")
            return "saved"

        result = run_with_transient_retry(
            operation,
            label="fight",
            on_retry=lambda attempt, _error: retries.append(attempt),
            sleeper=lambda _delay: None,
        )

        self.assertEqual(result, "saved")
        self.assertEqual(calls, 3)
        self.assertEqual(retries, [1, 2])


if __name__ == "__main__":
    unittest.main()
