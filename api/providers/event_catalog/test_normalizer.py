from __future__ import annotations

import unittest
from datetime import date

from api.providers.event_catalog.normalizer import parse_official_catalog


class OfficialCatalogNormalizerTests(unittest.TestCase):
    def test_reads_ufc_and_dwcs_json_ld(self) -> None:
        html = """
        <script type="application/ld+json">
        [{"@type":"SportsEvent","name":"Dana White's Contender Series: Season 10, Week 9",
          "startDate":"2026-10-06T19:00:00-05:00","url":"/event/dwcs-season-10-week-9"},
         {"@type":"SportsEvent","name":"UFC 332: Example vs Sample",
          "startDate":"2026-10-17T21:00:00-05:00","url":"/event/ufc-332"}]
        </script>
        """
        rows = parse_official_catalog(html, "ufc", "https://www.ufc.com/events")
        self.assertEqual([row["promotion_key"] for row in rows], ["dwcs", "ufc"])
        self.assertEqual(rows[0]["date"], date(2026, 10, 6))

    def test_reads_pfl_next_data_and_deduplicates(self) -> None:
        html = """
        <script id="__NEXT_DATA__" type="application/json">
          {"props":{"events":[{"title":"PFL Africa: Morocco","date":"2026-10-10",
          "slug":"pfl-africa-morocco"}]}}
        </script>
        """
        rows = parse_official_catalog(html, "pfl", "https://pflmma.com/events")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["promotion_key"], "pfl")
        self.assertTrue(rows[0]["external_url"].endswith("/events/pfl-africa-morocco"))

    def test_reads_pfl_sub_brand_heading_outside_matchups_link(self) -> None:
        html = """
        <section class="event-card">
          <time datetime="2026-10-18">Sat, Oct 18</time>
          <h3>AFRICA: SEMIFINALS - HW, WW, FW, &amp; BW</h3>
          <a href="/event/pfl-africa-semifinals">VIEW RESULTS</a>
        </section>
        """
        rows = parse_official_catalog(html, "pfl", "https://pflmma.com/events")
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0]["name"],
            "PFL AFRICA: SEMIFINALS - HW, WW, FW, & BW",
        )
        self.assertEqual(rows[0]["date"], date(2026, 10, 18))


if __name__ == "__main__":
    unittest.main()
