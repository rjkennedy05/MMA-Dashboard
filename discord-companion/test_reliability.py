import asyncio
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from setup_discord import SetupError
from state_store import load_state, save_state
from snapshot_merge import merge_external
from database_snapshot import SnapshotReader
from sync_discord import (
    DatabaseReader,
    Publisher,
    publish_research,
    fetch_data,
    final_bout,
)
from run_bot import EventService, make_client
from provider_runtime import configure_provider_core
from direct_sources import _odds_rows, convert_fights

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)


def fight(**changes):
    return {
        "fight_id": 10,
        "event_id": 1,
        "fighter_a_id": 11,
        "fighter_b_id": 12,
        "fighter_a": {"fighter_id": 11, "full_name": "Fighter A"},
        "fighter_b": {"fighter_id": 12, "full_name": "Fighter B"},
        "ruleset": "MMA",
        "fight_status": "scheduled",
        **changes,
    }


def data(**changes):
    return {
        "events": [
            {
                "event_id": 1,
                "event_name": "UFC Test Card",
                "event_date": "2026-10-12",
                "promotions": {"name": "UFC"},
            }
        ],
        "fights": [fight()],
        "odds": [],
        "links": [],
        **changes,
    }


class FreshnessTests(unittest.TestCase):
    def test_old_direct_card_cannot_hide_a_new_confirmed_database_result(self):
        stored = fight(
            fight_status="completed",
            winner_id=11,
            source_observed_at=NOW.isoformat(),
            result_confirmed_at=NOW.isoformat(),
        )
        direct = fight(fight_status="scheduled")
        state = {
            "events": {
                "1": {
                    "external_card": {
                        "checked_at": (NOW - timedelta(days=1)).isoformat(),
                        "event": {},
                        "fights": [direct],
                    }
                }
            }
        }
        merged = merge_external(data(fights=[stored]), state, NOW)
        self.assertEqual(merged["fights"][0]["winner_id"], 11)
        self.assertEqual(merged["fights"][0]["fight_status"], "completed")
        self.assertEqual(direct["fight_status"], "scheduled")

    def test_new_synthetic_bout_resolves_to_database_identity_and_preserves_omitted_bouts(
        self,
    ):
        direct = fight(
            fight_id="99999999999999999999999",
            fighter_a_id="111111",
            fighter_b_id="222222",
        )
        direct["fighter_a"]["fighter_id"] = "111111"
        direct["fighter_b"]["fighter_id"] = "222222"
        rows = [
            {
                "fight_id": direct["fight_id"],
                "fighter_id": "111111",
                "sportsbook_key": "draftkings",
                "american_odds": 110,
                "recorded_at": NOW.isoformat(),
            }
        ]
        state = {
            "events": {
                "1": {
                    "external_card": {
                        "checked_at": NOW.isoformat(),
                        "event": {},
                        "fights": [direct],
                    },
                    "direct_odds": rows,
                }
            }
        }
        merged = merge_external(
            data(
                fights=[
                    fight(),
                    fight(
                        fight_id=20,
                        fighter_a={"full_name": "C"},
                        fighter_b={"full_name": "D"},
                    ),
                ]
            ),
            state,
            NOW,
        )
        self.assertEqual(len(merged["fights"]), 2)
        self.assertEqual(merged["odds"][0]["fight_id"], 10)
        self.assertEqual(merged["odds"][0]["fighter_id"], 11)

    def test_direct_odds_keep_other_books_and_cannot_replace_newer_provider_prices(
        self,
    ):
        rows = [
            {
                "fight_id": 10,
                "fighter_id": 11,
                "sportsbook_key": "a",
                "american_odds": 110,
                "recorded_at": NOW.isoformat(),
            },
            {
                "fight_id": 10,
                "fighter_id": 11,
                "sportsbook_key": "b",
                "american_odds": 120,
                "recorded_at": NOW.isoformat(),
            },
        ]
        direct = {
            **rows[0],
            "american_odds": 150,
            "recorded_at": (NOW - timedelta(hours=1)).isoformat(),
        }
        merged = merge_external(
            data(odds=rows), {"events": {"1": {"direct_odds": [direct]}}}, NOW
        )
        self.assertEqual(merged["odds"], rows)
        direct.update(recorded_at=NOW.isoformat(), provider_updated_at=NOW.isoformat())
        merged = merge_external(
            data(odds=rows), {"events": {"1": {"direct_odds": [direct]}}}, NOW
        )
        self.assertTrue(any(r["sportsbook_key"] == "b" for r in merged["odds"]))

    def test_completed_header_does_not_finalize_a_bout_without_a_winner(self):
        self.assertFalse(final_bout(fight(fight_status="completed", winner_id=None)))
        self.assertTrue(final_bout(fight(fight_status="completed", winner_id=11)))
        self.assertTrue(final_bout(fight(fight_status="completed", result_type="draw")))

    def test_stale_overrides_expire_without_dropping_database_data(self):
        state = {
            "events": {
                "1": {
                    "external_card": {
                        "checked_at": (NOW - timedelta(days=10)).isoformat(),
                        "event": {"event_name": "Old Name"},
                        "fights": [fight(fight_id=90)],
                    }
                }
            }
        }
        self.assertEqual(
            merge_external(data(), state, NOW)["events"][0]["event_name"],
            "UFC Test Card",
        )


class HandshakeTests(unittest.TestCase):
    def reader(self, row):
        reader = DatabaseReader.__new__(DatabaseReader)
        reader.rows = lambda *a: [row]
        return reader

    def test_partial_is_not_enough_without_explicit_card_readiness(self):
        row = {
            "data_sync_run_id": 1,
            "status": "partial",
            "finished_at": NOW.isoformat(),
            "summary": {"run_mode": "daily", "requested_scope": "all"},
        }
        with self.assertRaisesRegex(SetupError, "not ready"):
            self.reader(row).wait_for_daily_sync(NOW, timeout_seconds=0)
        row["summary"].update(
            publishable=True, publication_readiness={"schema_version": 3, "ready": True,
                                                    "disputes": [], "checked_event_ids": []}
        )
        self.assertEqual(
            self.reader(row).wait_for_daily_sync(NOW, timeout_seconds=0), row
        )

    def test_odds_only_and_unfinished_runs_never_publish(self):
        row = {
            "data_sync_run_id": 1,
            "status": "success",
            "summary": {"run_mode": "daily", "requested_scope": "odds"},
        }
        with self.assertRaises(SetupError):
            self.reader(row).wait_for_daily_sync(NOW, timeout_seconds=0)
        row["summary"]["requested_scope"] = "all"
        row["status"] = "running"
        with self.assertRaises(SetupError):
            self.reader(row).wait_for_daily_sync(NOW, timeout_seconds=0)


class StateAndSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_provider_core(ROOT)

    def test_state_recovers_a_backup_and_refuses_unrecoverable_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sync-state.json"
            save_state(path, {"version": 1})
            save_state(path, {"version": 2})
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(load_state(path), {"version": 1})
            path.with_suffix(".json.bak").write_text("{broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_state(path)

    def test_two_fighters_at_one_book_are_required_for_coverage(self):
        board = {
            "fighter_one": "Fighter A",
            "fighter_two": "Fighter B",
            "sportsbooks": [
                {
                    "sportsbook": "DraftKings",
                    "fighter_one_odds": 110,
                    "fighter_two_odds": None,
                }
            ],
        }
        self.assertEqual(_odds_rows([board], [fight()], NOW, "FightOdds")[1], 0)
        board["sportsbooks"][0]["fighter_two_odds"] = -130
        rows, covered = _odds_rows([board], [fight()], NOW, "FightOdds")
        self.assertEqual(covered, 1)
        self.assertEqual(rows[0]["sportsbook_key"], "draftkings")

    def test_direct_reversal_preserves_saved_betting_sides(self):
        row = {
            "external_id": "bout",
            "fighter_a": {"external_id": "b", "name": "Fighter B", "winner": True},
            "fighter_b": {"external_id": "a", "name": "Fighter A"},
            "fight_status": "completed",
            "ruleset": "MMA",
        }
        rows, _ = convert_fights("espn_mma", {"event_id": 1}, [row], [fight()])
        self.assertEqual(rows[0]["fighter_a_id"], 11)
        self.assertEqual(str(rows[0]["winner_id"]), "12")

    def test_reused_source_identity_cannot_change_a_saved_opponent(self):
        previous = fight(_source_fight="espn_mma:bout")
        row = {
            "external_id": "bout",
            "fighter_a": {"external_id": "a", "name": "Fighter A"},
            "fighter_b": {"external_id": "c", "name": "Replacement"},
        }
        with self.assertRaisesRegex(SetupError, "reused source ID"):
            convert_fights("espn_mma", {"event_id": 1}, [row], [previous])

    def test_new_single_ticket_is_included_in_atomic_snapshot(self):
        tables = data()
        tables["events"][0]["event_name"] = "UFC Personal Card"
        stored = fight()
        stored["events"] = tables["events"][0]
        leg = {
            "ticket_id": 1,
            "fight_id": 10,
            "bet_side": "fighter_a",
            "leg_price": 110,
            "leg_order": 1,
            "fights": stored,
        }
        tables.update(
            bet_legs=[leg],
            bet_tickets=[
                {
                    "ticket_id": 1,
                    "owner_id": "00000000-0000-4000-8000-000000000001",
                    "ticket_type": "single",
                    "stake_units": 1,
                    "ticket_price": 110,
                    "bet_sportsbook": "DraftKings",
                    "bet_legs": [leg],
                }
            ],
        )
        result = fetch_data(SnapshotReader(tables), NOW, {})
        self.assertEqual(result["bets"]["1"][0]["type"], "single")
        self.assertEqual(result["bets"]["1"][0]["selection"], "Fighter A")

    def test_startup_before_the_daily_time_does_not_run_yesterdays_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            service = EventService(None, {}, Path(folder) / "state.json", ROOT)
            self.assertFalse(
                service.due("app", datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
            )
            self.assertTrue(service.due("app", NOW))


class ResearchTests(unittest.TestCase):
    def test_editing_research_updates_one_display_and_preserves_prior_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            publisher = Publisher.__new__(Publisher)
            publisher.bot = "1"
            publisher.recent = {}
            publisher.path = Path(folder) / "state.json"
            publisher.state = {"posts": {}, "events": {}}
            publisher.setup = {
                "guild_id": "123456789012345678",
                "channels": {"ufc": "2"},
            }
            messages = {}

            def request(method, route, body=None):
                if method == "GET" and "?" in route:
                    return list(messages.values())
                if method == "GET":
                    return messages[route.rsplit("/", 1)[-1]]
                if method == "POST":
                    msg = {**body, "id": str(len(messages) + 1), "author": {"id": "1"}}
                    messages[msg["id"]] = msg
                    return msg
                if method == "PATCH":
                    msg = messages[route.rsplit("/", 1)[-1]]
                    msg.update(body)
                    return msg
                if method == "DELETE":
                    messages.pop(route.rsplit("/", 1)[-1])
                    return None
                return None

            publisher.api = SimpleNamespace(request=request)
            event = {
                "event_id": 1,
                "event_name": "UFC Card",
                "promotions": {"name": "UFC"},
            }
            publish_research(publisher, event, "First research")
            publish_research(publisher, event, "Revised research")
            self.assertEqual(len(messages), 1)
            self.assertEqual(len(publisher.state["research_revisions"]["1"]), 1)
            self.assertTrue(
                all(
                    key.startswith("research:1:current:")
                    for key in publisher.state["posts"]
                )
            )


class PostRecoveryTests(unittest.TestCase):
    def test_lost_post_response_is_recovered_even_if_the_research_changed(self):
        with tempfile.TemporaryDirectory() as folder:
            publisher = Publisher.__new__(Publisher)
            publisher.bot = "1"
            publisher.recent = {}
            publisher.path = Path(folder) / "state.json"
            publisher.state = {"posts": {}, "events": {}}
            publisher.setup = {"guild_id": "123456789012345678"}
            messages = {}
            interrupt = [True]

            def request(method, route, body=None):
                if method == "GET" and "?" in route:
                    return list(messages.values())
                if method == "GET":
                    return messages[route.rsplit("/", 1)[-1]]
                if method == "POST":
                    message = {**body, "id": "1", "author": {"id": "1"}}
                    messages["1"] = message
                    if interrupt.pop():
                        raise OSError(
                            "Connection reset after Discord accepted the post"
                        )
                    return message
                if method == "PATCH":
                    messages["1"].update(body)
                    return messages["1"]

            publisher.api = SimpleNamespace(request=request)
            with self.assertRaises(OSError):
                publisher.post("research:1:current:0", "2", {"content": "Old analysis"})
            # Simulate a restart, whose durable intent precedes the successful POST.
            publisher.state = load_state(publisher.path)
            publisher.recent = {}
            publisher.post("research:1:current:0", "2", {"content": "New analysis"})
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages["1"]["content"], "New analysis")
            self.assertEqual(publisher.state["pending_posts"], {})


class CommandConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_wait_does_not_hold_the_command_lock(self):
        started, finish = Event(), Event()

        def prepare(now):
            started.set()
            finish.wait(2)
            return {"status": "success"}

        service = SimpleNamespace(
            setup={"guild_id": "123456789012345678"},
            due=lambda *a: True,
            prepare_app=prepare,
            sync_app=lambda *a: None,
            failed_job=lambda *a: None,
        )
        client = make_client(service, "unused")

        async def ready():
            pass

        client.wait_until_ready = ready
        task = asyncio.create_task(client.daily_loop())
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            await asyncio.wait_for(client.work.acquire(), 0.2)
            client.work.release()
        finally:
            finish.set()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await client.close()
