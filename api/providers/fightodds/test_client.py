from __future__ import annotations

import unittest

from api.providers.fightodds.client import FightOddsClient, ODDS_READY_SCRIPT


class _FakePage:
    def __init__(self, *, wait_error: Exception | None = None) -> None:
        self.wait_error = wait_error
        self.function_calls: list[tuple[str, int]] = []
        self.timeout_calls: list[int] = []

    def goto(self, url: str, *, wait_until: str, timeout: int) -> None:
        self.url = url
        self.goto_options = (wait_until, timeout)

    def wait_for_load_state(self, state: str, *, timeout: int) -> None:
        self.load_options = (state, timeout)

    def wait_for_function(self, script: str, *, timeout: int) -> None:
        self.function_calls.append((script, timeout))
        if self.wait_error:
            raise self.wait_error

    def wait_for_timeout(self, wait_ms: int) -> None:
        self.timeout_calls.append(wait_ms)

    def content(self) -> str:
        return "<html><table>rendered odds</table></html>"


class FightOddsClientTests(unittest.TestCase):
    def test_event_page_waits_for_rendered_fighter_prices(self) -> None:
        client = FightOddsClient()
        page = _FakePage()
        client._page = page

        html = client.get_event_odds("https://fightodds.io/odds/1/test")

        self.assertIn("rendered odds", html)
        self.assertEqual(page.function_calls, [(ODDS_READY_SCRIPT, 25000)])
        self.assertEqual(page.timeout_calls, [750])
        self.assertEqual(client.request_count, 1)

    def test_event_page_reports_render_timeout(self) -> None:
        client = FightOddsClient()
        client._page = _FakePage(wait_error=TimeoutError("slow page"))

        with self.assertRaisesRegex(
            RuntimeError,
            "did not render fighter moneylines within 25 seconds",
        ):
            client.get_event_odds("https://fightodds.io/odds/1/test")


if __name__ == "__main__":
    unittest.main()
