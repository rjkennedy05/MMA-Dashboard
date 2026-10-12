"""Read the same public card feed used by PFL's own event page."""

import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..event_catalog.client import OfficialCatalogClient
from .normalizer import OfficialPflCardError, card_metadata, normalize_card, trusted_event_url


class OfficialPflClient:
    def __init__(self, session=None, timeout=25):
        self.session = session or OfficialCatalogClient._session()
        self.timeout = timeout
        self.request_count = 0

    def get_card(self, entry):
        url = trusted_event_url(entry["external_url"])
        response = self.session.get(url, timeout=self.timeout,
            headers={"Cache-Control": "no-cache", "Accept": "text/html"})
        self.request_count += 1
        response.raise_for_status()
        trusted_event_url(response.url)
        metadata = card_metadata(response.text, entry)
        soup = BeautifulSoup(response.text, "html.parser")
        token = soup.select_one('input[name="_token"]')
        match = re.search(r"\bvar\s+fight_url\s*=\s*['\"]([^'\"]+)['\"]", response.text)
        if not token or not token.get("value") or not match:
            raise OfficialPflCardError("PFL did not provide its public card-feed connection.")
        endpoint = urlparse(match[1])
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        if (endpoint.scheme != "https" or endpoint.hostname != urlparse(response.url).hostname
                or endpoint.username or endpoint.password or endpoint.port not in {None, 443}
                or endpoint.path != "/smt/v2/" + slug or endpoint.query or endpoint.fragment):
            raise OfficialPflCardError("PFL's card endpoint does not belong to the selected official event.")
        # This POST is PFL's public read-only stats query. The token and session
        # are anonymous, short-lived, and never saved in state or reports.
        result = self.session.post(match[1], timeout=self.timeout, allow_redirects=False,
            headers={"X-CSRF-TOKEN": token["value"], "X-Requested-With": "XMLHttpRequest",
                     "Referer": response.url, "Accept": "application/json"})
        self.request_count += 1
        result.raise_for_status()
        if 300 <= result.status_code < 400:
            raise OfficialPflCardError("PFL redirected its public card endpoint; the card remains unverified.")
        return normalize_card(entry, metadata, result.json())
