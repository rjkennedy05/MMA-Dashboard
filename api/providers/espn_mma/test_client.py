from __future__ import annotations

import unittest
from datetime import date

import requests

from client import EspnMmaClient, EspnMmaError, EspnMmaNoFightCardError


class FakeResponse:
    def __init__(self, payload, status_error=None) -> None:
        self.payload = payload
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error:
            raise self.status_error

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payloads) -> None:
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, headers, params, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "params": params,
                "timeout": timeout,
            }
        )
        payload = self.payloads.pop(0)
        return payload if isinstance(payload, FakeResponse) else FakeResponse(payload)


class ErrorSession:
    def get(self, url, headers, params, timeout):
        return FakeResponse({}, requests.HTTPError("blocked"))


class ClientTests(unittest.TestCase):
    def test_scoreboard_requests_current_season_without_key(self) -> None:
        session = FakeSession(
            [{"events": [{"id": "600060394", "name": "PFL Charlotte"}]}]
        )
        client = EspnMmaClient(session=session)
        events = client.get_events_for_season(2026)

        self.assertEqual(events[0]["id"], "600060394")
        self.assertEqual(session.calls[0]["params"]["dates"], "2026")
        self.assertNotIn("limit", session.calls[0]["params"])
        self.assertEqual(client.request_count, 1)

    def test_ufc_client_uses_ufc_scoreboard_and_fightcenter(self) -> None:
        session = FakeSession(
            [
                {"events": []},
                {"cards": {"main": {"competitions": []}}},
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)
        client.get_events_for_season(2026)
        client.get_fightcenter("600059339")

        self.assertIn("/mma/ufc/scoreboard", session.calls[0]["url"])
        self.assertIn(
            "/mma/ufc/fightcenter/600059339",
            session.calls[1]["url"],
        )

    def test_unknown_league_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "pfl.*ufc"):
            EspnMmaClient(league="unknown")

    def test_events_are_deduplicated_across_seasons(self) -> None:
        session = FakeSession(
            [
                {"events": [{"id": "1", "name": "PFL One"}]},
                {
                    "events": [
                        {"id": "1", "name": "PFL One Updated"},
                        {"id": "2", "name": "PFL Two"},
                    ]
                },
            ]
        )
        events = EspnMmaClient(session=session).get_events(2025, 2026)
        self.assertEqual({event["id"] for event in events}, {"1", "2"})
        self.assertEqual(
            next(event for event in events if event["id"] == "1")["name"],
            "PFL One Updated",
        )

    def test_missing_events_list_is_explicit(self) -> None:
        client = EspnMmaClient(session=FakeSession([{}, {}, {}, {}]))
        with self.assertRaisesRegex(EspnMmaError, "events list"):
            client.get_events_for_season(2026)

    def test_http_failure_is_wrapped(self) -> None:
        client = EspnMmaClient(session=ErrorSession())
        with self.assertRaisesRegex(EspnMmaError, "request failed"):
            client.get_events_for_season(2026)

    def test_403_is_not_retried_before_fallback(self) -> None:
        client = EspnMmaClient()
        retries = client.session.get_adapter("https://").max_retries
        self.assertNotIn(403, retries.status_forcelist)

    def test_blocked_site_request_falls_back_to_web_calendar(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {},
                    status_error=requests.HTTPError("403 forbidden"),
                ),
                {
                    "events": [],
                    "leagues": [
                        {
                            "calendar": [
                                {
                                    "label": "UFC 330: Makhachev vs. Garry",
                                    "startDate": "2026-08-16T00:00Z",
                                    "event": {
                                        "$ref": (
                                            "http://sports.core.api.espn.pvt/"
                                            "v2/sports/mma/leagues/ufc/events/"
                                            "600059185?lang=en&region=us"
                                        )
                                    },
                                }
                            ]
                        }
                    ],
                },
            ]
        )
        client = EspnMmaClient(
            league="ufc",
            session=session,
        )
        events = client.get_events_for_season(2026)

        self.assertEqual(events[0]["id"], "600059185")
        self.assertEqual(events[0]["date"], "2026-08-16T00:00Z")
        self.assertEqual(session.calls[1]["params"], {"dates": "2026"})
        self.assertIn("site.web.api.espn.com", session.calls[1]["url"])
        self.assertEqual(client.event_source, "web_calendar")

    def test_season_request_rejects_current_event_from_ignored_year(self) -> None:
        session = FakeSession(
            [
                {
                    "events": [
                        {
                            "id": "current",
                            "name": "Current UFC event",
                            "date": "2026-09-01T00:00:00Z",
                        }
                    ],
                    "leagues": [
                        {
                            "calendar": [
                                {
                                    "label": "UFC Historical Event",
                                    "startDate": "2025-06-01T00:00:00Z",
                                    "event": {
                                        "$ref": (
                                            "https://sports.core.api.espn.com/"
                                            "v2/sports/mma/leagues/ufc/events/"
                                            "600050000"
                                        )
                                    },
                                }
                            ]
                        }
                    ],
                }
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)

        events = client.get_events_for_season(2025)

        self.assertEqual([event["id"] for event in events], ["600050000"])
        self.assertEqual(client.event_source, "site_calendar")

    def test_window_request_uses_web_scoreboard_after_site_403(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {},
                    status_error=requests.HTTPError("403 forbidden"),
                ),
                {
                    "events": [
                        {
                            "id": "600059185",
                            "name": "UFC 330: Makhachev vs. Machado Garry",
                            "date": "2026-08-16T01:00:00Z",
                        }
                    ]
                },
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)

        events = client.get_events_in_window(
            date(2026, 8, 10),
            date(2026, 11, 8),
        )

        self.assertEqual(events[0]["id"], "600059185")
        self.assertEqual(client.event_source, "web_scoreboard")
        self.assertEqual(len(session.calls), 2)

    def test_window_request_uses_core_after_both_scoreboards_fail(self) -> None:
        blocked = FakeResponse(
            {},
            status_error=requests.HTTPError("403 forbidden"),
        )
        session = FakeSession(
            [
                blocked,
                blocked,
                {
                    "items": [
                        {
                            "$ref": (
                                "https://sports.core.api.espn.com/v2/"
                                "sports/mma/leagues/ufc/events/600059185"
                            )
                        }
                    ]
                },
                {
                    "id": "600059185",
                    "name": "UFC 330: Makhachev vs. Machado Garry",
                    "date": "2026-08-16T01:00:00Z",
                    "competitions": [],
                },
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)

        events = client.get_events_in_window(
            date(2026, 8, 10),
            date(2026, 11, 8),
        )

        self.assertEqual(events[0]["id"], "600059185")
        self.assertEqual(client.event_source, "core_events")
        self.assertIn("sports.core.api.espn.com", session.calls[2]["url"])

    def test_history_window_requests_every_scoreboard_season(self) -> None:
        session = FakeSession(
            [
                {
                    "events": [
                        {
                            "id": f"event-{season}",
                            "name": f"UFC {season}",
                            "date": f"{season}-06-01T00:00:00Z",
                        }
                    ]
                }
                for season in range(2020, 2024)
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)

        events = client.get_events_in_window(
            date(2020, 1, 1),
            date(2023, 12, 31),
        )

        self.assertEqual(
            {event["id"] for event in events},
            {"event-2020", "event-2021", "event-2022", "event-2023"},
        )
        self.assertEqual(
            [call["params"]["dates"] for call in session.calls],
            ["2020", "2021", "2022", "2023"],
        )
        self.assertTrue(all(
            "site.api.espn.com" in call["url"]
            for call in session.calls
        ))
        self.assertEqual(client.event_source, "season_sweep")

    def test_core_uses_season_path_when_dates_filter_is_ignored(self) -> None:
        blocked = FakeResponse(
            {},
            status_error=requests.HTTPError("403 forbidden"),
        )
        session = FakeSession(
            [
                blocked,
                blocked,
                {
                    "items": [
                        {
                            "id": "old",
                            "name": "Old UFC event",
                            "date": "2010-01-01T00:00:00Z",
                        }
                    ]
                },
                {
                    "items": [
                        {
                            "id": "600059185",
                            "name": "UFC 330: Makhachev vs. Machado Garry",
                            "date": "2026-08-16T01:00:00Z",
                        }
                    ]
                },
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)

        events = client.get_events_in_window(
            date(2026, 8, 10),
            date(2026, 11, 8),
        )

        self.assertEqual([event["id"] for event in events], ["600059185"])
        self.assertIn("/leagues/ufc/events", session.calls[3]["url"])
        self.assertEqual(
            session.calls[3]["params"],
            {"season": "2026", "limit": "100"},
        )

    def test_fightcenter_uses_core_event_when_web_host_is_blocked(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {},
                    status_error=requests.HTTPError("403 forbidden"),
                ),
                {
                    "id": "600059185",
                    "competitions": [
                        {
                            "id": "401900001",
                            "competitors": [
                                {
                                    "id": "1",
                                    "order": 1,
                                    "athlete": {"displayName": "Fighter One"},
                                },
                                {
                                    "id": "2",
                                    "order": 2,
                                    "athlete": {"displayName": "Fighter Two"},
                                },
                            ],
                        }
                    ],
                },
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)

        payload = client.get_fightcenter("600059185")

        competitions = payload["cards"]["core"]["competitions"]
        self.assertEqual(competitions[0]["id"], "401900001")
        self.assertEqual(client.fightcenter_fallbacks, 1)

    def test_core_listing_without_competitions_is_cardless_not_provider_failure(self) -> None:
        session = FakeSession(
            [
                FakeResponse(
                    {},
                    status_error=requests.HTTPError("403 forbidden"),
                ),
                {"id": "600023342", "competitions": []},
            ]
        )
        client = EspnMmaClient(league="ufc", session=session)

        with self.assertRaises(EspnMmaNoFightCardError):
            client.get_fightcenter("600023342")


if __name__ == "__main__":
    unittest.main()
