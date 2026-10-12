from datetime import date, datetime
from unittest import TestCase
from unittest.mock import patch
from zoneinfo import ZoneInfo

from api.providers.event_catalog.sync import sync_official_catalogs


class CatalogWindowTests(TestCase):
    def run_catalog(self, html):
        with patch("api.providers.event_catalog.sync.OfficialCatalogClient") as client, \
             patch("api.providers.event_catalog.sync.OfficialCatalogImporter") as importer, \
             patch("api.providers.event_catalog.sync.datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 12, tzinfo=ZoneInfo("America/Chicago"))
            client.return_value.get_catalog.return_value = (html, "https://pflmma.com/events")
            client.return_value.request_count = 1
            importer.return_value.import_event.return_value = {"status": "matched", "event_id": 42}
            result = sync_official_catalogs(object(), requested_scope="pfl", past_days=0, future_days=7)
            return result, importer.return_value.import_event.call_count

    def test_verified_schedule_with_no_event_this_week_is_not_a_parser_failure(self):
        html = '''<div id="nav-upcoming"><div class="event-card-info">
        <h6>Sat, Nov 14</h6><h3>PFL Dubai</h3>
        <a href="/event/pfl-returns-to-dubai">MATCHUPS</a></div></div>'''
        result, writes = self.run_catalog(html)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["catalogs"]["pfl"]["events"], 0)
        self.assertEqual(result["catalogs"]["pfl"]["dated_events_on_page"], 1)
        self.assertEqual(result["issues"], [])
        self.assertEqual(writes, 0)

    def test_unrecognized_page_remains_a_failure(self):
        result, writes = self.run_catalog("<h1>Upcoming events</h1><p>Please try again later</p>")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["catalogs"]["pfl"]["status"], "failed")
        self.assertEqual(result["issues"][0]["code"], "CATALOG_UNAVAILABLE")
        self.assertEqual(writes, 0)

    def test_archival_json_ld_cannot_verify_the_current_schedule(self):
        html = '''<script type="application/ld+json">{"@type":"SportsEvent",
        "name":"PFL 1","startDate":"2018-06-07","url":"/event/2018-pfl-1"}</script>'''
        result, writes = self.run_catalog(html)
        self.assertEqual(result["catalogs"]["pfl"]["status"], "failed")
        self.assertEqual(writes, 0)

    def test_current_card_is_imported_with_the_official_date_and_identity(self):
        html = '''<div id="nav-upcoming"><div class="event-card-info">
        <h6>Fri, Oct 16</h6><h3>PFL Chicago 2</h3>
        <a href="/event/2026-chicago2">MATCHUPS</a></div></div>'''
        result, writes = self.run_catalog(html)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(writes, 1)
        self.assertEqual(result["entries"], [{"event_id": 42, "promotion_key": "pfl",
            "name": "PFL Chicago 2", "date": date(2026, 10, 16).isoformat(),
            "external_url": "https://pflmma.com/event/2026-chicago2"}])
