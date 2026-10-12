from __future__ import annotations

import unittest

from api.providers.fightodds.normalizer import (
    match_event,
    match_fight,
    parse_event_odds,
    parse_upcoming_events,
)


class FightOddsNormalizerTests(unittest.TestCase):
    def test_discovers_and_deduplicates_event_links(self) -> None:
        html = """
        <a href="/mma-events/9670/one-friday-fights-171">ONE Friday Fights 171</a>
        <a href="/mma-events/9670/one-friday-fights-171">ONE Friday Fights 171</a>
        <a href="/mma-events/9734/lfa-242-lozej-vs-bittencourt">LFA 242: Lozej vs. Bittencourt</a>
        """
        events = parse_upcoming_events(html)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["external_id"], "9670")
        self.assertIn("/odds/9670/one-friday-fights-171", events[0]["odds_url"])

    def test_matches_shortened_one_event_title(self) -> None:
        result = match_event(
            {"event_name": "ONE Friday Fights 171 & The Inner Circle 31"},
            [{"event_name": "ONE Friday Fights 171", "external_id": "9670"}],
        )
        self.assertEqual(result["status"], "matched")

    def test_parses_paired_fighter_rows_and_books(self) -> None:
        html = """
        <table><thead><tr><th>Fighters</th><th>BetOnline</th><th>DraftKings</th></tr></thead>
        <tbody>
          <tr><td><a href="/fighters/alpha-1">Alpha One</a></td><td><button>-150</button></td><td><button>-145</button></td></tr>
          <tr><td><a href="/fighters/beta-2">Beta Two</a></td><td><button>+130</button></td><td><button>+125</button></td></tr>
        </tbody></table>
        """
        fights = parse_event_odds(html)
        self.assertEqual(len(fights), 1)
        self.assertEqual(fights[0]["fighter_one"], "Alpha One")
        self.assertEqual(len(fights[0]["sportsbooks"]), 2)

    def test_matches_safe_same_card_name_variants(self) -> None:
        external = {
            "fighter_one": "Petsuphan Lookmuangpetch",
            "fighter_two": "Mahar Thway",
        }
        fights = [{
            "fight_id": 9272,
            "fighter_a": {"full_name": "Petsuphan Lookmuangpet"},
            "fighter_b": {"full_name": "Mahar Thway"},
        }]
        result = match_fight(external, fights)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["fight"]["fight_id"], 9272)
        self.assertEqual(result["orientation"], "forward")

    def test_matches_surname_first_with_minor_spelling_variant(self) -> None:
        external = {
            "fighter_one": "Sukhrob Iusupov",
            "fighter_two": "Brett Bye",
        }
        fights = [{
            "fight_id": 189,
            "fighter_a": {"full_name": "Isupov Sukhrob"},
            "fighter_b": {"full_name": "Brett Bye"},
        }]
        result = match_fight(external, fights)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["fight"]["fight_id"], 189)

    def test_rejects_shared_first_name_with_different_surname(self) -> None:
        external = {"fighter_one": "Davi Costa", "fighter_two": "Devon Lozej"}
        fights = [{
            "fight_id": 190,
            "fighter_a": {"full_name": "Davi Bittencourt"},
            "fighter_b": {"full_name": "Devon Lozej"},
        }]
        self.assertEqual(match_fight(external, fights)["status"], "unmatched")

    def test_rejects_stale_opponent_pairing(self) -> None:
        external = {"fighter_one": "Velihan Palit", "fighter_two": "Yuki Hamada"}
        fights = [{
            "fight_id": 9284,
            "fighter_a": {"full_name": "Velihan Palit"},
            "fighter_b": {"full_name": "Gump"},
        }]
        self.assertEqual(match_fight(external, fights)["status"], "unmatched")


if __name__ == "__main__":
    unittest.main()
