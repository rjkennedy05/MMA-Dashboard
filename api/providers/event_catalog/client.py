from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CATALOG_URLS = {
    "ufc": "https://www.ufc.com/events",
    "pfl": "https://pflmma.com/events",
}


class OfficialCatalogError(RuntimeError):
    pass


class OfficialCatalogClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = 25,
    ) -> None:
        self.session = session or self._session()
        self.timeout = timeout
        self.request_count = 0

    @staticmethod
    def _session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        session.mount("https://", HTTPAdapter(max_retries=retry))
        return session

    def get_catalog(self, key: str) -> tuple[str, str]:
        url = CATALOG_URLS.get(key)
        if not url:
            raise ValueError(f"Unsupported official catalog: {key}")
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
                    ),
                },
            )
            self.request_count += 1
            response.raise_for_status()
        except requests.RequestException as error:
            raise OfficialCatalogError(
                f"{key.upper()} official event catalog request failed: {error}"
            ) from error
        text = response.text
        if len(text) < 500:
            raise OfficialCatalogError(
                f"{key.upper()} official event catalog returned an incomplete page."
            )
        return text, response.url
