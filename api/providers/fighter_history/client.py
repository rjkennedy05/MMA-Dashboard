from __future__ import annotations

from urllib.parse import urljoin

import requests


SHERDOG_BASE_URL = "https://www.sherdog.com"
SHERDOG_SEARCH_URL = SHERDOG_BASE_URL + "/stats/fightfinder"


class FighterHistoryProviderError(RuntimeError):
    """Raised when the targeted history provider cannot return usable HTML."""


class SherdogHistoryClient:
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
            "User-Agent": "MMA-Dashboard/1.0 (personal history maintenance)",
        }

    def _get_html(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> tuple[str, str]:
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                params=params,
                timeout=self.timeout,
            )
            self.request_count += 1
            response.raise_for_status()
        except requests.RequestException as error:
            raise FighterHistoryProviderError(
                f"History fallback request failed: {error}"
            ) from error

        html = response.text
        if not html or "<html" not in html.casefold():
            raise FighterHistoryProviderError(
                "History fallback returned unusable HTML."
            )
        return html, response.url

    def search(self, fighter_name: str) -> tuple[str, str]:
        return self._get_html(
            SHERDOG_SEARCH_URL,
            {"SearchTxt": fighter_name},
        )

    def profile(self, profile_url: str) -> tuple[str, str]:
        return self._get_html(urljoin(SHERDOG_BASE_URL, profile_url))
