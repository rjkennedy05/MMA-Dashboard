from __future__ import annotations

from typing import Any

import requests


LFA_UPCOMING_URL = "https://www.lfa.com/events/"
LFA_PAST_URL = (
    "https://www.lfa.com/?eventDisplay=past&post_type=tribe_events"
)
SHERDOG_ORGANIZATION_URL = (
    "https://www.sherdog.com/organizations/"
    "Legacy-Fighting-Alliance-LFA-11339"
)
SHERDOG_BASE_URL = "https://www.sherdog.com"


class LfaProviderError(RuntimeError):
    """Raised when an LFA provider returns an unusable response."""


class LfaClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 45,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.request_count = 0
        self.headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "MMA-Dashboard/1.0 (personal data sync)",
        }

    def _get_html(self, url: str) -> str:
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            self.request_count += 1
            response.raise_for_status()
        except requests.RequestException as error:
            raise LfaProviderError(
                f"LFA provider request failed for {url}: {error}"
            ) from error

        html = response.text
        if not html or "<html" not in html.casefold():
            raise LfaProviderError(
                f"LFA provider returned unusable HTML for {url}."
            )
        return html

    def get_official_upcoming(self) -> str:
        return self._get_html(LFA_UPCOMING_URL)

    def get_official_past(self) -> str:
        return self._get_html(LFA_PAST_URL)

    def get_sherdog_index(self) -> str:
        return self._get_html(SHERDOG_ORGANIZATION_URL)

    def get_sherdog_event(self, event_url: str) -> str:
        url = event_url
        if url.startswith("/"):
            url = SHERDOG_BASE_URL + url
        if not url.startswith(("http://", "https://")):
            raise LfaProviderError(
                f"Invalid Sherdog LFA event URL: {event_url}"
            )
        return self._get_html(url)
