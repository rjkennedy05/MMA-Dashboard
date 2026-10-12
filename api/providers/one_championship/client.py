from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests


EVENTS_URL = "https://www.onefc.com/events/"
ALLOWED_HOST = "www.onefc.com"


class OneChampionshipError(RuntimeError):
    """Raised when ONE Championship returns an unusable response."""


class OneChampionshipClient:
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
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
            raise OneChampionshipError(
                f"Refusing unexpected ONE Championship URL: {url}"
            )

        try:
            response = self.session.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            self.request_count += 1
            response.raise_for_status()
        except requests.RequestException as error:
            raise OneChampionshipError(
                f"ONE Championship request failed: {error}"
            ) from error

        html = response.text
        if not html or "onefc.com" not in html.casefold():
            raise OneChampionshipError(
                "ONE Championship returned an empty or unexpected page."
            )
        return html

    def _get_json(self, url: str) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
            raise OneChampionshipError(
                f"Refusing unexpected ONE Championship URL: {url}"
            )
        try:
            response = self.session.get(
                url,
                headers={**self.headers, "Accept": "application/json"},
                timeout=self.timeout,
            )
            self.request_count += 1
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as error:
            raise OneChampionshipError(
                f"ONE Championship request failed: {error}"
            ) from error
        except ValueError as error:
            raise OneChampionshipError(
                "ONE Championship returned an invalid event status."
            ) from error
        if not isinstance(payload, dict):
            raise OneChampionshipError(
                "ONE Championship event status is not a JSON object."
            )
        return payload

    def get_event_listing(self) -> str:
        return self._get_html(EVENTS_URL)

    def get_event_page(self, event_url: str) -> str:
        return self._get_html(event_url)

    def get_event_status(self, status_url: str) -> dict[str, Any]:
        return self._get_json(status_url)
