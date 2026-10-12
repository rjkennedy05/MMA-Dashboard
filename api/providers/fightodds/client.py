from __future__ import annotations

from typing import Any


BASE_URL = "https://fightodds.io"
UPCOMING_EVENTS_URL = f"{BASE_URL}/upcoming-mma-events"

ODDS_READY_SCRIPT = r"""
() => Array.from(document.querySelectorAll("table")).some((table) => {
  const fighters = table.querySelectorAll('a[href^="/fighters/"]');
  const text = table.innerText || "";
  return fighters.length >= 2 && /(?:^|\s)[+-]\d{2,5}(?:\s|$)/m.test(text);
})
"""


class FightOddsClient:
    """Read a small number of rendered public pages with one Chromium session."""

    def __init__(self, *, headless: bool = True) -> None:
        self.headless = headless
        self.request_count = 0
        self._playwright: Any = None
        self._browser: Any = None
        self._page: Any = None

    def __enter__(self) -> "FightOddsClient":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError(
                "FightOdds fallback requires Playwright. Run "
                "'python -m pip install -r api/requirements.txt' and "
                "'python -m playwright install chromium'."
            ) from error

        try:
            self._playwright = sync_playwright().start()
            try:
                self._browser = self._playwright.chromium.launch(
                    headless=self.headless
                )
            except Exception:
                # Reuse installed Chrome only as a binary. This still opens a
                # fresh temporary profile and never touches a signed-in one.
                self._browser = self._playwright.chromium.launch(
                    channel="chrome", headless=self.headless
                )
            self._page = self._browser.new_page()
        except Exception:
            self.__exit__(None, None, None)
            raise RuntimeError(
                "FightOdds could not start Chromium or Chrome. Run the "
                "included dependency/browser installer."
            ) from None
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._page is not None:
            self._page.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._page = None
        self._browser = None
        self._playwright = None

    def read(
        self,
        url: str,
        *,
        wait_ms: int = 750,
        ready_script: str | None = None,
        ready_timeout_ms: int = 25000,
    ) -> str:
        if self._page is None:
            raise RuntimeError("FightOdds browser is not open.")

        self.request_count += 1
        self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._page.wait_for_load_state("domcontentloaded", timeout=60000)
        if ready_script:
            try:
                self._page.wait_for_function(
                    ready_script,
                    timeout=ready_timeout_ms,
                )
            except Exception as error:
                raise RuntimeError(
                    "FightOdds page did not render fighter moneylines within "
                    f"{ready_timeout_ms // 1000} seconds."
                ) from error
        self._page.wait_for_timeout(wait_ms)
        return str(self._page.content())

    def get_upcoming_events(self) -> str:
        return self.read(UPCOMING_EVENTS_URL, wait_ms=2500)

    def get_event_odds(self, url: str) -> str:
        return self.read(
            url,
            wait_ms=750,
            ready_script=ODDS_READY_SCRIPT,
            ready_timeout_ms=25000,
        )
