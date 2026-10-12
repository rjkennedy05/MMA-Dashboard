import unittest
from datetime import date

from normalizer import (
    dashboard_event_date,
    event_in_window,
    merge_event_listings,
    parse_official_events,
    parse_sherdog_fights,
    parse_sherdog_index,
)


OFFICIAL_HTML = """
<html><body><script type="application/ld+json">
[
 {"@context":"https://schema.org","@type":"Event",
  "name":"LFA 239 &#8211; Francischinelli vs. Hanes",
  "description":"Live on VICE TV and ESPN Deportes",
  "url":"https://www.lfa.com/event/lfa-239-ventura-california/",
  "startDate":"2026-08-21T00:00:00-07:00",
  "location":{"@type":"Place","name":"Ventura County Event Center",
   "address":{"addressLocality":"Ventura","addressRegion":"CA"}}},
 {"@context":"https://schema.org","@type":"Event",
  "name":"LFA 241 - TO BE ANNOUNCED",
  "url":"https://www.lfa.com/event/lfa-241-to-be-announced/",
  "startDate":"2026-09-11T00:00:00-07:00"}
]
</script></body></html>
"""


SHERDOG_INDEX_HTML = """
<html><body>
<div id="upcoming_tab"><table>
 <tr itemscope itemtype="http://schema.org/Event">
  <td><meta itemprop="startDate" content="2026-08-21T00:00:00+00:00"></td>
  <td><a itemprop="url" href="/events/LFA-239-Francischinelli-vs-Hanes-113687">
   <span itemprop="name">LFA 239 - Francischinelli vs. Hanes</span></a></td>
  <td itemprop="location">Ventura County Fairgrounds, Ventura, California, United States</td>
 </tr>
</table></div>
<div id="recent_tab"><table>
 <tr itemscope itemtype="http://schema.org/Event">
  <td><meta itemprop="startDate" content="2026-07-31T00:00:00+00:00"></td>
  <td><a itemprop="url" href="/events/LFA-238-Distrito-1-113533">
   <span itemprop="name">LFA 238 - Distrito #1</span></a></td>
  <td itemprop="location">Nilson Nelson Gymnasium, Brasilia, Federal District, Brazil</td>
 </tr>
</table></div>
</body></html>
"""


UPCOMING_CARD_HTML = """
<html><body>
<div itemprop="subEvent" itemscope itemtype="http://schema.org/Event">
 <div class="fight_card">
  <div class="fighter left_side" itemprop="performer">
   <a itemprop="url" href="/fighter/Luis-Francischinelli-428715"><span itemprop="name">Luis Francischinelli</span></a>
   <span class="final_result yet_to_come">yet to come</span>
  </div>
  <div class="versus"><b>MAIN EVENT</b><span class="weight_class">Welterweight</span></div>
  <div class="fighter right_side" itemprop="performer">
   <a itemprop="url" href="/fighter/Jonathan-Hanes-229473"><span itemprop="name">Jonathan Hanes</span></a>
   <span class="final_result yet_to_come">yet to come</span>
  </div>
 </div>
</div>
<table class="new_table upcoming">
 <tr itemprop="subEvent" itemscope itemtype="http://schema.org/Event">
  <td>10</td>
  <td itemprop="performer"><a itemprop="url" href="/fighter/Gianni-Vazquez-188217"><span itemprop="name">Gianni<br/>Vazquez</span></a></td>
  <td><span class="weight_class">Flyweight</span></td>
  <td itemprop="performer"><a itemprop="url" href="/fighter/Adrian-Garcia-346773"><span itemprop="name">Adrian<br/>Garcia</span></a></td>
  <td></td>
 </tr>
</table>
</body></html>
"""


COMPLETED_CARD_HTML = """
<html><body>
<div itemprop="subEvent" itemscope itemtype="http://schema.org/Event">
 <div class="fight_card">
  <div class="fighter left_side" itemprop="performer">
   <a itemprop="url" href="/fighter/Herbeth-Sousa-121337"><span itemprop="name">Herbeth Sousa</span></a>
   <span class="final_result win">win</span>
  </div>
  <div class="versus"><span class="weight_class">Bantamweight</span></div>
  <div class="fighter right_side" itemprop="performer">
   <a itemprop="url" href="/fighter/Paulo-Portillo-198157"><span itemprop="name">Paulo Portillo</span></a>
   <span class="final_result loss">loss</span>
  </div>
 </div>
 <table class="fight_card_resume"><tr>
  <td><em>Match</em><br/>14</td><td><em>Method</em><br/>Technical Submission</td>
  <td><em>Round</em><br/>1</td><td><em>Time</em><br/>4:55</td>
 </tr></table>
</div>
<table class="new_table result">
 <tr itemprop="subEvent" itemscope itemtype="http://schema.org/Event">
  <td>13</td>
  <td itemprop="performer"><a itemprop="url" href="/fighter/Gabriel-Vinicius-454929"><span itemprop="name">Gabriel Vinicius</span></a><span class="final_result win">win</span></td>
  <td><span class="weight_class">Welterweight</span></td>
  <td itemprop="performer"><a itemprop="url" href="/fighter/Claudio-Nardo-310855"><span itemprop="name">Claudio Nardo</span></a><span class="final_result loss">loss</span></td>
  <td class="winby"><b>TKO (Elbows and Punches)</b></td><td>2</td><td>0:42</td>
 </tr>
</table>
</body></html>
"""


class LfaNormalizerTests(unittest.TestCase):
    def test_parses_official_calendar(self):
        events = parse_official_events(OFFICIAL_HTML, "upcoming")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["external_id"], "lfa-239")
        self.assertEqual(events[0]["venue"], "Ventura County Event Center")
        self.assertEqual(events[0]["watch_platform"], "VICE TV / ESPN Deportes")
        self.assertEqual(dashboard_event_date(events[0]), date(2026, 8, 21))

    def test_merges_official_and_sherdog_by_lfa_number(self):
        official = parse_official_events(OFFICIAL_HTML, "upcoming")
        sherdog = parse_sherdog_index(SHERDOG_INDEX_HTML)
        merged = merge_event_listings(official, sherdog)
        by_id = {event["external_id"]: event for event in merged}

        self.assertEqual(set(by_id), {"lfa-238", "lfa-239", "lfa-241"})
        self.assertTrue(by_id["lfa-239"]["sherdog_url"].endswith("113687"))
        self.assertEqual(by_id["lfa-238"]["status"], "completed")
        self.assertTrue(
            event_in_window(by_id["lfa-239"], date(2026, 8, 1), date(2026, 9, 1))
        )

    def test_parses_upcoming_card_in_main_event_order(self):
        event = parse_official_events(OFFICIAL_HTML, "upcoming")[0]
        fights = parse_sherdog_fights(event, UPCOMING_CARD_HTML)

        self.assertEqual(len(fights), 2)
        self.assertEqual(fights[0]["fighter_a"]["name"], "Luis Francischinelli")
        self.assertEqual(fights[0]["weight_class"], "Welterweight")
        self.assertEqual(fights[0]["fight_status"], "scheduled")
        self.assertEqual(fights[1]["fighter_b"]["external_id"], "346773")

    def test_parses_completed_results(self):
        event = {
            "external_id": "lfa-238",
            "name": "LFA 238: Distrito #1",
            "date": parse_official_events(OFFICIAL_HTML, "upcoming")[0]["date"],
        }
        fights = parse_sherdog_fights(event, COMPLETED_CARD_HTML)

        self.assertEqual(len(fights), 2)
        self.assertEqual(fights[0]["fight_status"], "completed")
        self.assertTrue(fights[0]["fighter_a"]["winner"])
        self.assertEqual(fights[0]["method"], "Technical Submission")
        self.assertEqual(fights[0]["finish_time_seconds"], 295)
        self.assertEqual(fights[1]["method"], "TKO (Elbows and Punches)")
        self.assertEqual(fights[1]["finish_round"], 2)
        self.assertEqual(fights[1]["finish_time_seconds"], 42)


if __name__ == "__main__":
    unittest.main()
