from __future__ import annotations

import unittest

from normalizer import (
    dashboard_event_date,
    event_external_id,
    event_fights,
    event_location,
    event_promotion_key,
    event_status,
    fighters,
    fight_matchup_identity,
    fighter_profile,
    finish_method,
    finish_round,
    finish_time_seconds,
    is_placeholder_fight,
    is_title_fight,
    matchup_label,
    normalized_status,
    result_type,
    scheduled_rounds,
    watch_platform,
    weight_class,
    winner_external_id,
)


EVENT = {
    "id": "600059746",
    "name": "PFL New York: Nurmagomedov vs. Colgan",
    "date": "2026-07-31T20:30Z",
    "status": {
        "type": {
            "state": "post",
            "completed": True,
            "description": "Final",
        }
    },
    "links": [
        {
            "rel": ["summary", "desktop", "event"],
            "href": "https://www.espn.com/mma/fightcenter/_/id/600059746/league/pfl",
        }
    ],
    "competitions": [
        {
            "id": "401873872",
            "date": "2026-07-31T23:00Z",
            "format": {"regulation": {"periods": 5}},
            "venue": {
                "fullName": "UBS Arena",
                "address": {
                    "city": "Elmont",
                    "state": "NY",
                    "country": "USA",
                },
            },
            "broadcasts": [{"names": ["ESPN", "ESPN+"]}],
            "competitors": [],
        }
    ],
}

DETAILED_FIGHT = {
    "id": "401873872",
    "date": "2026-07-31T23:00:00+00:00",
    "type": {"text": "Lightweight"},
    "types": [{"text": "Lightweight Title"}],
    "matchNumber": 1,
    "note": "Lightweight - Main Event - Title Fight",
    "status": {
        "clock": "222.0",
        "displayClock": "3:42",
        "period": 1,
        "type": {
            "state": "post",
            "completed": True,
            "description": "Final",
        },
        "result": {
            "displayName": "KO/TKO",
            "displayDescription": "Punches",
        },
    },
    "competitors": [
        {
            "id": "4878438",
            "order": 2,
            "winner": False,
            "athlete": {"displayName": "Archie Colgan"},
        },
        {
            "id": "4726566",
            "order": 1,
            "winner": True,
            "athlete": {"displayName": "Usman Nurmagomedov"},
        },
    ],
}

FIGHTCENTER = {
    "cards": {
        "main": {
            "competitions": [DETAILED_FIGHT],
        }
    }
}


class NormalizerTests(unittest.TestCase):
    def test_tba_matchups_are_provider_placeholders(self) -> None:
        fight = {
            "id": "placeholder-1",
            "competitors": [
                {
                    "order": 1,
                    "id": "tba-a",
                    "athlete": {"id": "tba-a", "displayName": "Opponent TBA"},
                },
                {
                    "order": 2,
                    "id": "tba-b",
                    "athlete": {"id": "tba-b", "displayName": "TBA"},
                },
            ],
        }
        self.assertTrue(is_placeholder_fight(fight))
        self.assertEqual(matchup_label(fight), "Opponent TBA vs TBA")
        self.assertFalse(is_placeholder_fight(DETAILED_FIGHT))

    def test_event_metadata(self) -> None:
        self.assertEqual(event_external_id(EVENT), "600059746")
        self.assertEqual(dashboard_event_date(EVENT).isoformat(), "2026-07-31")
        self.assertEqual(event_status(EVENT), "completed")
        self.assertEqual(event_location(EVENT)["venue"], "UBS Arena")
        self.assertEqual(watch_platform(EVENT), "ESPN / ESPN+")

    def test_ufc_and_dwcs_promotion_routing(self) -> None:
        ufc_event = {
            **EVENT,
            "name": "UFC Fight Night: Medić vs. Rodriguez",
        }
        dwcs_event = {
            **EVENT,
            "name": "Dana White's Contender Series: Season 10, Week 1",
        }
        self.assertEqual(event_promotion_key(ufc_event), "ufc")
        self.assertEqual(event_promotion_key(dwcs_event), "dwcs")

    def test_detail_merge_preserves_scoreboard_round_format(self) -> None:
        fight = event_fights(EVENT, FIGHTCENTER)[0]
        self.assertEqual(scheduled_rounds(fight), 5)
        self.assertTrue(is_title_fight(fight))
        self.assertEqual(finish_method(fight), "KO/TKO (Punches)")

    def test_different_competition_ids_for_same_matchup_are_deduplicated(self) -> None:
        scoreboard_fight = {
            **DETAILED_FIGHT,
            "id": "scoreboard-competition",
            "status": {"type": {"state": "pre"}},
            "competitors": [
                {
                    **row,
                    "id": f"scoreboard-slot-{index}",
                    "athlete": {
                        **row["athlete"],
                        "id": f"athlete-{index}",
                    },
                }
                for index, row in enumerate(DETAILED_FIGHT["competitors"], start=1)
            ],
        }
        detailed_fight = {
            **DETAILED_FIGHT,
            "id": "fightcenter-competition",
            "competitors": [
                {
                    **row,
                    "id": f"fightcenter-slot-{index}",
                    "athlete": {
                        **row["athlete"],
                        "id": f"alternate-feed-athlete-{index}",
                    },
                }
                for index, row in enumerate(DETAILED_FIGHT["competitors"], start=1)
            ],
        }
        event = {**EVENT, "competitions": [scoreboard_fight]}
        fightcenter = {"cards": {"main": {"competitions": [detailed_fight]}}}

        fights_found = event_fights(event, fightcenter)

        self.assertEqual(len(fights_found), 1)
        self.assertIn(
            fights_found[0]["id"],
            {"scoreboard-competition", "fightcenter-competition"},
        )
        self.assertEqual(
            fight_matchup_identity(scoreboard_fight),
            fight_matchup_identity(detailed_fight),
        )

    def test_fighter_identity_prefers_stable_athlete_id_over_slot_id(self) -> None:
        fight = {
            **DETAILED_FIGHT,
            "competitors": [
                {
                    **row,
                    "id": f"competition-slot-{index}",
                    "athlete": {
                        **row["athlete"],
                        "id": f"stable-athlete-{index}",
                    },
                }
                for index, row in enumerate(DETAILED_FIGHT["competitors"], start=1)
            ],
        }
        fighter_a, fighter_b = fighters(fight)
        self.assertEqual(
            {fighter_a["external_id"], fighter_b["external_id"]},
            {"stable-athlete-1", "stable-athlete-2"},
        )

    def test_fighters_winner_and_result(self) -> None:
        fighter_a, fighter_b = fighters(DETAILED_FIGHT)
        self.assertEqual(fighter_a["name"], "Usman Nurmagomedov")
        self.assertEqual(fighter_b["name"], "Archie Colgan")
        self.assertEqual(winner_external_id(DETAILED_FIGHT), "4726566")
        self.assertEqual(normalized_status(DETAILED_FIGHT), "completed")
        self.assertEqual(result_type(DETAILED_FIGHT), "win")
        self.assertEqual(finish_round(DETAILED_FIGHT), 1)
        self.assertEqual(finish_time_seconds(DETAILED_FIGHT), 222)

    def test_current_fighter_profile_normalization(self) -> None:
        profile = fighter_profile({
            "displayRecord": "14-6-1",
            "athlete": {
                "age": 32,
                "dateOfBirth": "1994-07-13T07:00Z",
                "displayHeight": "5' 7\"",
                "displayReach": "69\"",
                "country": "Mexico",
                "stance": {"text": "Orthodox"},
                "headshot": {"href": "https://example.test/fighter.png"},
            },
        })
        self.assertEqual(profile["record_summary"], "14-6-1")
        self.assertEqual(profile["age_snapshot"], 32)
        self.assertEqual(profile["date_of_birth"], "1994-07-13")
        self.assertEqual(profile["height_inches"], 67)
        self.assertEqual(profile["reach_inches"], 69)
        self.assertEqual(profile["stance"], "Orthodox")
        self.assertEqual(profile["nationality"], "Mexico")
        self.assertEqual(profile["image_url"], "https://example.test/fighter.png")

    def test_upcoming_fight_has_no_finish_values(self) -> None:
        fight = {
            **DETAILED_FIGHT,
            "status": {
                "clock": "0.0",
                "period": 0,
                "type": {
                    "state": "pre",
                    "completed": False,
                    "description": "Scheduled",
                },
                "result": {},
            },
        }
        self.assertEqual(normalized_status(fight), "scheduled")
        self.assertIsNone(finish_round(fight))
        self.assertIsNone(finish_time_seconds(fight))

    def test_core_scalar_fields_do_not_crash_normalization(self) -> None:
        event = {
            **EVENT,
            "status": "pre",
            "competitions": [
                {
                    **EVENT["competitions"][0],
                    "venue": "TBD",
                    "broadcasts": ["ESPN+"],
                }
            ],
        }
        fight = {
            **DETAILED_FIGHT,
            "format": "3 rounds",
            "status": {"type": "pre"},
            "competitors": [
                {
                    **row,
                    "athlete": row["athlete"]["displayName"],
                    "displayName": row["athlete"]["displayName"],
                }
                for row in DETAILED_FIGHT["competitors"]
            ],
        }

        self.assertEqual(event_status(event), "upcoming")
        self.assertEqual(
            event_location(event),
            {
                "venue": None,
                "city": None,
                "state_region": None,
                "country": None,
            },
        )
        self.assertIsNone(watch_platform(event))
        self.assertEqual(scheduled_rounds(fight), 5)
        self.assertEqual(normalized_status(fight), "scheduled")
        self.assertEqual(
            {fighter["name"] for fighter in fighters(fight)},
            {"Usman Nurmagomedov", "Archie Colgan"},
        )

    def test_title_type_and_fighter_gender_fill_missing_weight_class(self) -> None:
        fight = {
            **DETAILED_FIGHT,
            "type": None,
            "types": [{"text": "Featherweight Title"}],
            "competitors": [
                {
                    **row,
                    "athlete": {
                        **row["athlete"],
                        "gender": "FEMALE",
                    },
                }
                for row in DETAILED_FIGHT["competitors"]
            ],
        }
        self.assertEqual(weight_class(fight), "Women's Featherweight")


if __name__ == "__main__":
    unittest.main()
