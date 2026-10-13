import unittest
from datetime import date

from normalizer import (
    dashboard_event_date,
    enrich_event,
    event_in_window,
    parse_event_listing,
    parse_fights,
    event_status_url,
    ruleset,
    scheduled_rounds_value,
    weight_class,
)


LISTING_HTML = """
<html><body>onefc.com
  <div class="simple-post-card is-event">
    <a class="title" href="https://www.onefc.com/events/onefightnight46/"
       title="ONE Fight Night 46"><h3>ONE Fight Night 46</h3></a>
    <div class="datetime" data-timestamp="1786755600"></div>
    <div class="location">Lumpinee Stadium, Bangkok</div>
  </div>
  <div class="simple-post-card is-event">
    <a class="title" href="https://www.onefc.com/events/one-samurai-2/"
       title="ONE SAMURAI 2"><h3>ONE SAMURAI 2</h3></a>
    <div class="datetime" data-timestamp="1786177800"></div>
    <div class="location">EBARA WAVE Arena Ota, Tokyo</div>
  </div>
</body></html>
"""


DETAIL_HTML = """
<html><body>onefc.com
  <script>window.eventStatusUrl = 'https://www.onefc.com/wp-json/public/v2/events/546347';</script>
  <div class="event-live-status is-finished"></div>
  <script type="application/ld+json">
  {"@context":"https://schema.org","@type":"Event",
   "location":{"@type":"Place","name":"Lumpinee Stadium",
   "address":{"@type":"PostalAddress","addressLocality":"Bangkok",
   "addressRegion":"Bangkok","addressCountry":"TH"}}}
  </script>
  <div class="event-matchup">
    <div class="title">Bantamweight MMA World Championship</div>
    <a class="face face1" href="https://www.onefc.com/athletes/enkh-orgil-baatarkhuu/">
      <div class="sticker"></div>
    </a>
    <a class="face face2" href="https://www.onefc.com/athletes/elbek-alyshov/">
      <div class="sticker is-win"><span><em>WIN</em>
        <span class="opacity-50 d-none d-xxl-inline-block">TKO (R2)</span>
      </span></div>
    </a>
    <div class="stats"><table><tr class="vs">
      <td><a href="https://www.onefc.com/athletes/enkh-orgil-baatarkhuu/"
        title="Enkh-Orgil Baatarkhuu">Enkh-Orgil Baatarkhuu</a></td>
      <th>VS</th>
      <td><a href="https://www.onefc.com/athletes/elbek-alyshov/"
        title="Elbek Alyshov">Elbek Alyshov</a></td>
    </tr></table></div>
  </div>
  <div class="event-matchup">
    <div class="title">Featherweight Submission Grappling</div>
    <a class="face face1" href="https://www.onefc.com/athletes/ruan-alvarenga/"><div class="sticker"></div></a>
    <a class="face face2" href="https://www.onefc.com/athletes/meyram-maquine-alves/"><div class="sticker"></div></a>
    <div class="stats"><table><tr class="vs">
      <td><a href="https://www.onefc.com/athletes/ruan-alvarenga/" title="Ruan Alvarenga">Ruan Alvarenga</a></td>
      <th>VS</th>
      <td><a href="https://www.onefc.com/athletes/meyram-maquine-alves/" title="Meyram Maquine Alves">Meyram Maquine Alves</a></td>
    </tr></table></div>
  </div>
</body></html>
"""


class OneChampionshipNormalizerTests(unittest.TestCase):
    def test_explicit_cancellation_does_not_cancel_the_other_bout(self):
        html = DETAIL_HTML.replace('<div class="sticker"></div>', '<div class="sticker">CANCELLED</div>', 1)
        fights = parse_fights(parse_event_listing(LISTING_HTML)[0], html)
        self.assertEqual(fights[0]["fight_status"], "cancelled")
        self.assertEqual(fights[1]["fight_status"], "scheduled")

    def setUp(self):
        self.events = parse_event_listing(LISTING_HTML)
        self.event = self.events[0]

    def test_parses_official_event_listing(self):
        self.assertEqual(len(self.events), 2)
        self.assertEqual(self.event["external_id"], "onefightnight46")
        self.assertEqual(self.event["name"], "ONE Fight Night 46")

    def test_uses_chicago_calendar_date(self):
        self.assertEqual(dashboard_event_date(self.event), date(2026, 8, 14))
        self.assertTrue(
            event_in_window(
                self.event,
                date(2026, 8, 14),
                date(2026, 8, 14),
            )
        )

    def test_enriches_event_from_official_schema(self):
        enriched = enrich_event(
            self.event,
            DETAIL_HTML,
            status_payload={"is_past": True, "is_finished": True},
        )
        self.assertEqual(enriched["status"], "completed")
        self.assertEqual(enriched["venue"], "Lumpinee Stadium")
        self.assertEqual(enriched["city"], "Bangkok")
        self.assertEqual(enriched["country"], "TH")
        self.assertEqual(enriched["watch_platform"], "Prime Video")
        self.assertEqual(
            event_status_url(DETAIL_HTML),
            "https://www.onefc.com/wp-json/public/v2/events/546347",
        )

    def test_preserves_ruleset_and_completed_result(self):
        fights = parse_fights(self.event, DETAIL_HTML)
        mma = fights[0]
        self.assertEqual(len(fights), 2)
        self.assertEqual(mma["ruleset"], "MMA")
        self.assertEqual(mma["weight_class"], "Bantamweight")
        self.assertTrue(mma["is_title_fight"])
        self.assertEqual(mma["scheduled_rounds"], 5)
        self.assertEqual(mma["fight_status"], "completed")
        self.assertEqual(mma["method"], "TKO")
        self.assertEqual(mma["finish_round"], 2)
        self.assertEqual(
            mma["fighter_b"]["external_id"], "elbek-alyshov"
        )
        self.assertTrue(mma["fighter_b"]["winner"])

    def test_submission_grappling_is_one_round(self):
        grappling = parse_fights(self.event, DETAIL_HTML)[1]
        self.assertEqual(grappling["ruleset"], "Submission Grappling")
        self.assertEqual(grappling["scheduled_rounds"], 1)
        self.assertEqual(grappling["fight_status"], "scheduled")

    def test_ruleset_helpers_cover_mixed_one_cards(self):
        self.assertEqual(ruleset("Flyweight Muay Thai"), "Muay Thai")
        self.assertEqual(ruleset("Featherweight Kickboxing"), "Kickboxing")
        self.assertEqual(weight_class("Women's Atomweight MMA"), "Women's Atomweight")
        self.assertEqual(
            scheduled_rounds_value("Lightweight MMA World Championship"),
            5,
        )


if __name__ == "__main__":
    unittest.main()
