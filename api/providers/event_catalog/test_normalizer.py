from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from api.providers.event_catalog.normalizer import parse_official_catalog
from api.providers.event_catalog.importer import event_match_score, OfficialCatalogImporter
from api.providers.event_identity import AmbiguousEventError


FIXTURES = Path(__file__).with_name("fixtures")


class OfficialCatalogNormalizerTests(unittest.TestCase):
    def test_current_ufc_schedule_reads_main_card_timestamps_and_titles(self) -> None:
        rows = parse_official_catalog(
            (FIXTURES / "ufc_schedule_20261012.html").read_text(),
            "ufc", "https://www.ufc.com/events",
        )
        self.assertEqual(
            [(row["name"], row["date"]) for row in rows],
            [("UFC Fight Night: Allen vs Duncan", date(2026, 10, 10)),
             ("UFC Fight Night: Buckley vs Malott", date(2026, 10, 17)),
             ("UFC 333: Volkanovski vs Evloev", date(2026, 10, 24)),
             ("UFC Fight Night: Moicano vs Nolan", date(2026, 10, 31))],
        )
        self.assertEqual(len({row["external_id"] for row in rows}), 4)

    def test_current_pfl_schedule_reads_yearless_dates_in_their_sections(self) -> None:
        rows = parse_official_catalog(
            (FIXTURES / "pfl_schedule_20261012.html").read_text(),
            "pfl", "https://pflmma.com/events", reference_date=date(2026, 10, 12),
        )
        self.assertEqual(
            [(row["name"], row["date"]) for row in rows],
            [("PFL MENA 11", date(2026, 10, 2)),
             ("PFL Africa Morocco", date(2026, 10, 10)),
             ("PFL Chicago 2", date(2026, 10, 16)),
             ("PFL Dubai", date(2026, 11, 14)),
             ("PFL MENA 12", date(2026, 12, 11)),
             ("PFL Lyon", date(2026, 12, 19))],
        )

    def test_yearless_dates_cross_new_year_without_redating_archives(self) -> None:
        html = '''
        <div id="nav-upcoming"><div class="event-card-info">
          <h6>Sat, Jan 2</h6><h3>PFL Dubai</h3><a href="/event/dubai">MATCHUPS</a>
        </div></div>
        <div id="nav-past"><div class="event-card-info">
          <h6>Fri, Dec 18</h6><h3>PFL Lyon</h3><a href="/event/lyon">RESULTS</a>
        </div></div>
        <div id="nav-all"><div class="event-card-info">
          <h6>Fri, Dec 18</h6><h3>PFL Old Card</h3><a href="/event/old">RESULTS</a>
        </div></div>'''
        rows = parse_official_catalog(html, "pfl", "https://pflmma.com/events",
                                      reference_date=date(2026, 12, 30))
        self.assertEqual([row["date"] for row in rows], [date(2026, 12, 18), date(2027, 1, 2)])
        rows = parse_official_catalog(html, "pfl", "https://pflmma.com/events",
                                      reference_date=date(2027, 1, 1))
        self.assertEqual([row["date"] for row in rows], [date(2026, 12, 18), date(2027, 1, 2)])

    def test_stale_upcoming_weekday_is_not_assigned_a_new_year(self) -> None:
        html = '''<div id="nav-upcoming"><div class="event-card-info">
          <h6>Sat, Oct 10</h6><h3>PFL Old Card</h3><a href="/event/old">MATCHUPS</a>
        </div></div>'''
        self.assertEqual(parse_official_catalog(html, "pfl", "https://pflmma.com/events",
                                                reference_date=date(2026, 10, 12)), [])

    def test_full_weekday_and_explicit_archive_year_are_resolved_independently(self) -> None:
        html = '''<div id="nav-upcoming"><div class="event-card-info">
          <h6>Thursday, Oct 15</h6><h3>PFL Dubai</h3><a href="/event/dubai">MATCHUPS</a>
        </div></div><div id="nav-all"><div class="event-card-info">
          <h6>Fri, Sep 30</h6><h3>PFL Old Card</h3><a href="/event/2022-old">RESULTS</a>
        </div></div>'''
        rows = parse_official_catalog(html, "pfl", "https://pflmma.com/events",
                                      reference_date=date(2026, 10, 12))
        self.assertEqual([row["date"] for row in rows], [date(2022, 9, 30), date(2026, 10, 15)])

    def test_ufc_timestamp_uses_central_time_at_the_new_year_boundary(self) -> None:
        html = '''<div class="c-card-event--result__info">
          <h3><a href="/event/ufc-999">Example vs Sample</a></h3>
          <div class="c-card-event--result__date" data-main-card-timestamp="1798765200"></div>
        </div>'''
        rows = parse_official_catalog(html, "ufc", "https://www.ufc.com/events")
        self.assertEqual(rows[0]["date"], date(2026, 12, 31))

    def test_ticket_dates_and_neighbor_cards_cannot_supply_missing_event_dates(self) -> None:
        html = '''<div><div data-timestamp="1792281600">Ticket presale</div>
        <article class="c-card-event--result"><div class="c-card-event--result__info">
          <h3><a href="/event/ufc-333">Volkanovski vs Evloev</a></h3>
          <div class="c-card-event--result__date" data-main-card-timestamp="invalid"></div>
        </div></article>
        <article><h3>UFC 334</h3><time datetime="2026-11-14"></time>
          <a href="/event/ufc-334">View card</a></article></div>'''
        rows = parse_official_catalog(html, "ufc", "https://www.ufc.com/events")
        self.assertEqual([row["external_id"] for row in rows], ["ufc:ufc-334"])

    def test_generic_ticket_link_does_not_create_a_catalog_event(self) -> None:
        html = '''<section><h3>UFC 333</h3><time datetime="2026-10-24"></time>
          <a href="https://tickets.example/event/ufc-333">Tickets</a></section>'''
        self.assertEqual(parse_official_catalog(html, "ufc", "https://www.ufc.com/events"), [])

    def test_short_pfl_city_title_matches_the_detailed_main_event_title(self) -> None:
        score = event_match_score("PFL Chicago 2", "PFL Chicago: Carmouche vs. Bishop 2")
        self.assertGreaterEqual(score, 0.64)
        self.assertLess(event_match_score("PFL Chicago 2", "PFL Dubai: Carmouche vs. Bishop 2"), 0.64)
        self.assertLess(event_match_score("PFL 2", "PFL Chicago: Carmouche vs. Bishop 2"), 0.64)
        self.assertEqual(event_match_score("PFL Chicago 2", "PFL Chicago 3"), 0)
        self.assertEqual(event_match_score("PFL Chicago 2", "PFL Chicago 3: A vs Bishop 2"), 0)

    def test_matching_pfl_city_titles_still_require_one_unambiguous_event(self) -> None:
        importer = OfficialCatalogImporter.__new__(OfficialCatalogImporter)
        importer._events_near = lambda entry: [
            {"event_id": i, "event_date": "2026-10-16", "event_name": title}
            for i, title in [(1, "PFL Chicago: Carmouche vs. Bishop 2"),
                             (2, "PFL Chicago: Another vs. Opponent 2")]
        ]
        with self.assertRaises(AmbiguousEventError):
            importer._find_existing({"date": date(2026, 10, 16), "name": "PFL Chicago 2"})

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
