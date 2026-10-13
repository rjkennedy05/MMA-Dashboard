import unittest
from copy import deepcopy
from datetime import date

from normalizer import (
    dashboard_event_date,
    enrich_event,
    event_in_window,
    event_stats_url,
    merge_event_listings,
    parse_event_listing,
    parse_fights,
)


LISTING_HTML = """
<html><body>
<div class="events_item"><div class="events_card">
 <div class="events_card_partners"><img alt="BKFC+ App"><img alt="BKFC on Fubo Sports"></div>
 <a href="/events/bkfc-fight-night-sturgis"><h3 class="events_card_heading">BKFC FIGHT NIGHT STURGIS ACHESON vs JONES</h3></a>
 <div data-event-date-est>August 8, 2026 9:00 PM</div>
 <div class="events_card_location"><p>THE BUFFALO CHIP - STURGIS, SD</p></div>
</div></div>
</body></html>
"""


EVENT_HTML = """
<html><body>
<div class="hero-event-card"><div class="hero-event-card_meta_item">
 <p class="text-size-1-25">THE BUFFALO CHIP - STURGIS, SD</p>
</div></div>
<div data-bout data-AthleteBlueUUID="blue-uuid" data-AthleteRedUUID="red-uuid">
 <div class="fight-card_header"><h3 class="fight-card_heading">Championship Bout</h3><h3 class="fight-card_heading">Cruiserweight</h3></div>
 <a aria-label="BRYANT ACHESON" href="/fighters/bryant-acheson"></a>
 <a aria-label="MIKE JONES" href="/fighters/mike-jones"></a>
 <a aria-label="BRYANT ACHESON" href="/fighters/bryant-acheson"></a>
 <a aria-label="MIKE JONES" href="/fighters/mike-jones"></a>
</div>
<script>
 const FINAL_STATS = '';
 const LIVE_STATS = 'https://xapi.mmareg.com/api/v2/bkfc/?type=json&amp;modifier=event-stats&amp;id=1354';
</script>
</body></html>
"""


STATS = {
    "Bouts": {
        "Bout1": {
            "BoutID": 9259,
            "BoutUUID": "bout-uuid",
            "AthleteBlueUUID": "blue-uuid",
            "BlueFirstName": "Bryant",
            "BlueLastName": "Acheson",
            "BlueResult": "win",
            "AthleteRedUUID": "red-uuid",
            "RedFirstName": "Mike",
            "RedLastName": "Jones",
            "RedResult": "lose",
            "Weightclass": "Cruiserweight",
            "ChampionshipBout": 1,
            "TotalRounds": 6,
            "WinMethod": "TKO",
            "WinTechnique": "Doctor Stoppage",
            "RoundEnded": 3,
            "RoundEndedTime": "01:38",
        }
    }
}


PRELIM_HTML = """
<html><body><div data-bout data-AthleteBlueUUID="blue-prelim" data-AthleteRedUUID="red-prelim">
 <div class="fight-card_header"><h3 class="fight-card_heading">Free Fight</h3><h3 class="fight-card_heading">Welterweight</h3></div>
 <a class="fight-card_headshot" href="/fighters/blue-prelim">Win Loss</a>
 <a href="/fighters/blue-prelim"><p class="fight-card_name">BLUE FIGHTER</p></a>
 <a href="/fighters/red-prelim"><p class="fight-card_name">RED FIGHTER</p></a>
 <a class="fight-card_headshot" href="/fighters/red-prelim">Win Loss</a>
</div></body></html>
"""


FUTURE_CARD_HTML = """
<html><body>
<div data-bout data-AthleteBlueUUID="carlos-uuid" data-AthleteRedUUID="opponent-uuid">
 <div class="fight-card_header"><h3 class="fight-card_heading">Welterweight</h3></div>
 <a class="fight-card_headshot" aria-label="Win Loss Draw No Contest" href="/fighters/carlos-trinidad"></a>
 <a href="/fighters/carlos-trinidad"><p class="fight-card_name">CARLOS TRINIDAD</p></a>
 <a href="/fighters/opponent"><p class="fight-card_name">BRYCE HENRY</p></a>
 <a class="fight-card_headshot" aria-label="Win Loss Draw No Contest" href="/fighters/opponent"></a>
</div>
<div data-bout data-AthleteBlueUUID="garside-uuid" data-AthleteRedUUID="taylor-uuid">
 <div class="fight-card_header"><h3 class="fight-card_heading">Bantamweight</h3></div>
 <a aria-label="LEWIS GARSIDE" href="/fighters/lewis-garside"></a>
 <a aria-label="BRADLEY TAYLOR" href="/fighters/bradley-taylor"></a>
</div>
</body></html>
"""


class BkfcNormalizerTests(unittest.TestCase):
    def test_explicit_bout_cancellation_is_not_mistaken_for_a_completed_result(self):
        stats = deepcopy(STATS)
        stats["Bouts"]["Bout1"].update(WinMethod="Cancelled", BlueResult="", RedResult="")
        event = parse_event_listing(LISTING_HTML, "completed")[0]
        fights = parse_fights(event, EVENT_HTML, stats)
        self.assertEqual(fights[0]["fight_status"], "cancelled")
        self.assertFalse(fights[0]["fighter_a"]["winner"])

    def test_parses_official_event_listing(self):
        event = parse_event_listing(LISTING_HTML, "upcoming")[0]
        self.assertEqual(event["external_id"], "bkfc-fight-night-sturgis")
        self.assertEqual(event["venue"], "THE BUFFALO CHIP")
        self.assertEqual(event["city"], "Sturgis")
        self.assertEqual(event["country"], "United States")
        self.assertEqual(event["watch_platform"], "BKFC+ / Fubo Sports")
        self.assertEqual(dashboard_event_date(event), date(2026, 8, 8))
        self.assertTrue(
            event_in_window(event, date(2026, 8, 1), date(2026, 9, 1))
        )

    def test_merges_same_slug_and_keeps_completed_status(self):
        upcoming = parse_event_listing(LISTING_HTML, "upcoming")
        completed = parse_event_listing(LISTING_HTML, "completed")
        merged = merge_event_listings(upcoming, completed)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["status"], "completed")

    def test_extracts_stats_url_and_enriches_location(self):
        event = parse_event_listing(LISTING_HTML, "upcoming")[0]
        enriched = enrich_event(event, EVENT_HTML)
        self.assertEqual(enriched["venue"], "THE BUFFALO CHIP")
        self.assertEqual(
            event_stats_url(EVENT_HTML),
            "https://xapi.mmareg.com/api/v2/bkfc/?type=json&modifier=event-stats&id=1354",
        )

    def test_parses_scheduled_bare_knuckle_bout(self):
        event = parse_event_listing(LISTING_HTML, "upcoming")[0]
        fight = parse_fights(event, EVENT_HTML)[0]
        self.assertEqual(fight["fighter_a"]["name"], "Bryant Acheson")
        self.assertEqual(fight["ruleset"], "Bare Knuckle Boxing")
        self.assertEqual(fight["fight_status"], "scheduled")
        self.assertEqual(fight["scheduled_rounds"], 5)
        self.assertTrue(fight["is_title_fight"])

    def test_enriches_completed_result_from_official_stats(self):
        event = parse_event_listing(LISTING_HTML, "completed")[0]
        fight = parse_fights(event, EVENT_HTML, STATS)[0]
        self.assertEqual(fight["external_id"], "bout-uuid")
        self.assertEqual(fight["fight_status"], "completed")
        self.assertTrue(fight["fighter_a"]["winner"])
        self.assertEqual(fight["result_type"], "tko")
        self.assertEqual(fight["method"], "TKO (Doctor Stoppage)")
        self.assertEqual(fight["finish_round"], 3)
        self.assertEqual(fight["finish_time_seconds"], 98)
        self.assertEqual(fight["scheduled_rounds"], 5)

    def test_parses_prelim_links_without_aria_labels(self):
        event = parse_event_listing(LISTING_HTML, "upcoming")[0]
        fight = parse_fights(event, PRELIM_HTML)[0]
        self.assertEqual(fight["fighter_a"]["name"], "Blue Fighter")
        self.assertEqual(fight["fighter_b"]["name"], "Red Fighter")

    def test_ignores_combined_outcome_labels_on_future_cards(self):
        event = parse_event_listing(LISTING_HTML, "upcoming")[0]
        fights = parse_fights(event, FUTURE_CARD_HTML)
        self.assertEqual(fights[0]["fighter_a"]["name"], "Carlos Trinidad")
        self.assertEqual(fights[0]["fighter_b"]["name"], "Bryce Henry")
        self.assertEqual(fights[1]["fighter_a"]["name"], "Lewis Garside")
        self.assertEqual(fights[1]["fighter_b"]["name"], "Bradley Taylor")


if __name__ == "__main__":
    unittest.main()
