from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

import requests


BKFC_BASE_URL = "https://www.bkfc.com"
BKFC_UPCOMING_URL = f"{BKFC_BASE_URL}/events"
BKFC_PAST_URL = f"{BKFC_BASE_URL}/event-past/past"


class BkfcProviderError(RuntimeError):
    """Raised when an official BKFC endpoint returns unusable data."""


class BkfcClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 45,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.request_count = 0
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/json",
            "User-Agent": "MMA-Dashboard/1.0 (personal data sync)",
        }

    def _get(self, url: str) -> requests.Response:
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            self.request_count += 1
            response.raise_for_status()
            return response
        except requests.RequestException as error:
            raise BkfcProviderError(
                f"BKFC provider request failed for {url}: {error}"
            ) from error

    def _get_html(self, url: str) -> str:
        response = self._get(url)
        html = response.text
        if not html or "<html" not in html.casefold():
            raise BkfcProviderError(
                f"BKFC provider returned unusable HTML for {url}."
            )
        return html

    def get_upcoming(self) -> str:
        return self._get_html(BKFC_UPCOMING_URL)

    def get_past(self) -> str:
        return self._get_html(BKFC_PAST_URL)

    def get_event_page(self, event_url: str) -> str:
        url = event_url
        if url.startswith("/"):
            url = BKFC_BASE_URL + url
        if not url.startswith(("http://", "https://")):
            raise BkfcProviderError(f"Invalid BKFC event URL: {event_url}")
        return self._get_html(url)

    def get_event_stats(self, stats_url: str) -> dict[str, Any]:
        if not stats_url.startswith(("http://", "https://")):
            raise BkfcProviderError(f"Invalid BKFC stats URL: {stats_url}")
        response = self._get(stats_url)
        try:
            payload = response.json()
        except ValueError:
            # MMAReg requests XML in its live stats URL even when the response
            # headers sometimes describe JSON. Accept either actual format.
            text = response.text.lstrip("\ufeff \t\r\n")
            if not text.startswith("<") or re.search(
                r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I
            ):
                raise BkfcProviderError(
                    "BKFC results feed returned unusable JSON/XML."
                ) from None
            try:
                root = ElementTree.fromstring(text)
            except ElementTree.ParseError:
                raise BkfcProviderError(
                    "BKFC results feed returned malformed XML."
                ) from None
            stats = root if root.tag == "EventStats" else root.find("EventStats")
            if stats is None:
                raise BkfcProviderError(
                    "BKFC results feed returned no event stats."
                )

            def values(node):
                return {
                    child.tag: values(child)
                    if len(child)
                    else (child.text or "").strip()
                    for child in node
                }

            payload = values(stats)
        if isinstance(payload, dict) and isinstance(
            payload.get("EventStats"), dict
        ):
            payload = payload["EventStats"]
        if isinstance(payload, dict) and isinstance(payload.get("Bouts"), list):
            payload["Bouts"] = {
                f"Bout{index}": row
                for index, row in enumerate(payload["Bouts"], 1)
                if isinstance(row, dict)
            }
        if not isinstance(payload, dict) or not isinstance(
            payload.get("Bouts"), dict
        ):
            raise BkfcProviderError(
                "BKFC official stats endpoint returned no bout collection."
            )
        return payload
