from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
from postgrest import SyncPostgrestClient

from api.providers.atomic import AtomicImportClient, import_batch, wrap_import_client
from api.providers.database import CompleteQuery, read_rows
from api.providers.event_catalog.importer import (
    OfficialCatalogImporter,
    event_match_score,
)
from datetime import date
from api.providers.event_identity import matching_event, AmbiguousEventError
from api.providers.errors import safe_error
from api.providers.configuration import validate_project_urls
from api.providers.persistence import save_entity
from api.providers.test_fight_identity import MemoryDatabase
from api.sync.cards import import_card, process_cards
from api.sync.lease import SyncLease, ImportBusyError, ImportLeaseLost
from api.sync.readiness import CARD_FLAGS, finalize_readiness, resolve_scope
from api.sync.data_quality import audit_upcoming_coverage
from api.sync.test_data_quality import FakeSupabase


class PaginationTests(unittest.TestCase):
    def test_real_sdk_paging_survives_a_server_cap_and_preserves_query(self):
        calls = []

        def transport(request):
            calls.append(request.url)
            params = request.url.params
            start = int(params.get("offset", "0"))
            rows = [{"fighter_id": i} for i in range(1, 8)][start : start + 2]
            return httpx.Response(200, json=rows)

        client = SyncPostgrestClient(
            "https://example.invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        )
        query = CompleteQuery(client.table("fighters"), "fighters").select("fighter_id")
        saved = str(query.query.request.params)
        rows = query.execute().data
        self.assertEqual([r["fighter_id"] for r in rows], list(range(1, 8)))
        self.assertEqual(str(query.query.request.params), saved)
        self.assertEqual(len(calls), 5)

    def test_keyset_rejects_repeated_pages_instead_of_returning_partial_data(self):
        class Query:
            def order(self, *a):
                return self

            def limit(self, *a):
                return self

            def gt(self, *a):
                return self

            def execute(self):
                return SimpleNamespace(data=[{"id": 1}])

        with self.assertRaisesRegex(RuntimeError, "repeated"):
            read_rows(Query, "id")


class CardBatchTests(unittest.TestCase):
    def database(self):
        database = MemoryDatabase(False)
        database.rows.update(events=[], fighters=[], fights=[])
        return database, AtomicImportClient(database)

    def test_no_physical_entity_or_mapping_is_written_until_whole_card_commits(self):
        raw, client = self.database()
        with import_batch(client) as batch:
            event = save_entity(client, "event", {"event_name": "Card"}, 7, "card")
            a = save_entity(client, "fighter", {"full_name": "A"}, 7, "a")
            b = save_entity(client, "fighter", {"full_name": "B"}, 7, "b")
            fight = save_entity(
                client,
                "fight",
                {
                    "event_id": event["internal_id"],
                    "fighter_a_id": a["internal_id"],
                    "fighter_b_id": b["internal_id"],
                },
                7,
                "bout",
            )
            self.assertEqual(raw.rows["external_ids"], [])
            self.assertEqual(raw.rows["events"], [])
        self.assertGreater(batch.saved_ids[fight["internal_id"]], 0)
        self.assertEqual(
            raw.rows["fights"][0]["event_id"], raw.rows["events"][0]["event_id"]
        )
        self.assertEqual(len(raw.rows["external_ids"]), 4)

    def test_partial_profile_patch_keeps_names_visible_inside_the_card(self):
        def transport(request):
            if request.url.path.endswith("mma_apply_import_batch"):
                return httpx.Response(200, json={"ids": {}, "results": []})
            start = int(request.url.params.get("offset", "0"))
            return httpx.Response(
                200,
                json=[{"fighter_id": 11, "full_name": "Fighter A"}]
                if start == 0
                else [],
            )

        raw = SyncPostgrestClient(
            "https://example.invalid",
            http_client=httpx.Client(transport=httpx.MockTransport(transport)),
        )
        client = AtomicImportClient(raw)
        with import_batch(client):
            save_entity(client, "fighter", {"nickname": "Ace"}, 7, "athlete-a", 11)
            rows = (
                client.table("fighters").select("fighter_id,full_name").execute().data
            )
            self.assertEqual(rows[0]["full_name"], "Fighter A")
            self.assertEqual(rows[0]["nickname"], "Ace")

    def test_raw_sdk_clients_are_wrapped_and_both_import_paths_share_one_context(self):
        from supabase import create_client
        import importlib

        sdk = create_client("https://example.invalid", "offline-placeholder")
        self.assertIsInstance(wrap_import_client(sdk), AtomicImportClient)
        self.assertIs(
            importlib.import_module("providers.atomic").AtomicImportClient,
            AtomicImportClient,
        )

    def test_omitted_scheduled_bouts_are_reported_without_cancelling_or_removing_them(
        self,
    ):
        raw = MemoryDatabase()
        raw.rows["fights"].append({**raw.rows["fights"][0], "fight_id": 101})
        importer = SimpleNamespace(
            supabase=raw,
            import_event=lambda *a, **k: {"status": "updated", "event_id": 5},
            import_fight=lambda *a, **k: {
                "status": "updated",
                "fight_id": 100,
                "fight_status": "scheduled",
            },
        )
        saved, _ = import_card(importer, {"event_id": 5}, [{}])
        self.assertEqual(saved["unconfirmed_omissions"], [101])
        self.assertEqual(
            [r["fight_status"] for r in raw.rows["fights"]], ["scheduled", "scheduled"]
        )

    def test_empty_listings_are_not_reported_as_successful_source_coverage(self):
        with self.assertRaisesRegex(RuntimeError, "no recognizable events"):
            process_cards(
                None, {}, None, None, [], [], "bkfc", [], "", None, None, None
            )

    def test_normalization_failure_keeps_all_previous_database_data(self):
        raw, client = self.database()
        before = deepcopy(raw.rows)
        with self.assertRaises(ValueError):
            with import_batch(client):
                save_entity(client, "event", {"event_name": "Card"}, 7, "card")
                save_entity(client, "fighter", {"full_name": "A"}, 7, "a")
                raise ValueError("Last opponent is ambiguous")
        self.assertEqual(raw.rows, before)


class LeaseTests(unittest.TestCase):
    def client(self, acquired=True, renew=True):
        self.calls = []

        def rpc(name, args):
            self.calls.append((name, args))
            result = (
                {"acquired": acquired, "fence": 7}
                if name == "mma_claim_sync_lease"
                else renew
            )
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=result))

        return SimpleNamespace(rpc=rpc)

    @patch.dict(os.environ, {}, clear=True)
    def test_owned_lease_is_passed_to_children_and_restored_after_exit(self):
        client = self.client()
        with SyncLease(client, interval=1000) as parent:
            self.assertEqual(os.environ["MMA_SYNC_LEASE_FENCE"], "7")
            with SyncLease(client, interval=1000) as child:
                self.assertTrue(child.inherited)
            self.assertNotIn("mma_release_sync_lease", [n for n, _ in self.calls])
        self.assertNotIn("MMA_SYNC_LEASE_HOLDER", os.environ)
        self.assertEqual([n for n, _ in self.calls].count("mma_release_sync_lease"), 1)

    @patch.dict(os.environ, {}, clear=True)
    def test_busy_import_is_refused_and_dry_run_never_claims(self):
        client = self.client(acquired=False)
        with self.assertRaises(ImportBusyError):
            with SyncLease(client):
                pass
        self.calls.clear()
        with SyncLease(client, dry_run=True):
            pass
        self.assertEqual(self.calls, [])

    @patch.dict(os.environ, {}, clear=True)
    def test_lost_heartbeat_stops_the_writer(self):
        client = self.client(renew=False)
        with SyncLease(client, interval=0.001) as lease:
            self.assertTrue(lease.lost.wait(1))
            with self.assertRaises(ImportLeaseLost):
                lease.ensure_owned()


class ReadinessTests(unittest.TestCase):
    def args(self, **overrides):
        return SimpleNamespace(
            **{
                "mode": "daily",
                "requested_scope": "all",
                "skip_catalog": False,
                "skip_odds": False,
                "dry_run": False,
                **{flag: False for flag in CARD_FLAGS.values()},
                **overrides,
            }
        )

    def summary(self):
        return {
            "provider_runs": {
                **{key: {"status": "completed"} for key in CARD_FLAGS},
                "official_catalog": {"status": "completed"},
            },
            "quality_audit": {"status": "complete", "issues": []},
            "warnings": [],
            "errors": [],
            "odds_status": "completed",
        }

    def test_odds_only_cannot_be_mistaken_for_a_complete_card_run(self):
        args = self.args(**{flag: True for flag in CARD_FLAGS.values()})
        args.requested_scope = resolve_scope(args)
        self.assertEqual(args.requested_scope, "odds")
        self.assertFalse(finalize_readiness(self.summary(), args)["publishable"])

    def test_all_failed_card_sources_are_failed_not_successful_partial(self):
        summary = self.summary()
        for key in CARD_FLAGS:
            summary["provider_runs"][key]["status"] = "failed"
        self.assertEqual(finalize_readiness(summary, self.args())["status"], "failed")
        self.assertFalse(summary["publishable"])

    def test_optional_odds_gaps_can_publish_but_a_failed_card_source_cannot(self):
        summary = self.summary()
        summary["odds_status"] = "completed_with_gaps"
        self.assertTrue(finalize_readiness(summary, self.args())["publishable"])
        self.assertEqual(summary["status"], "partial")
        summary["provider_runs"]["bkfc"]["status"] = "partial"
        self.assertFalse(finalize_readiness(summary, self.args())["publishable"])

    def test_a_missing_official_near_term_event_blocks_publication(self):
        summary = self.summary()
        summary["quality_audit"]["issues"] = [
            {
                "code": "DETAIL_SOURCE_GAP",
                "event_date": datetime.now(timezone.utc).date().isoformat(),
            }
        ]
        self.assertFalse(finalize_readiness(summary, self.args())["publishable"])


class IdentityAndCoverageTests(unittest.TestCase):
    def test_ambiguous_and_similar_titles_require_review_but_distinct_numbers_do_not(
        self,
    ):
        rows = [{"event_id": 1, "event_name": "LFA 101: Test"}]
        self.assertEqual(matching_event(rows, "LFA 101 renamed", "lfa"), 1)
        self.assertIsNone(matching_event(rows, "LFA 102: Test", "lfa"))
        with self.assertRaises(AmbiguousEventError):
            matching_event(rows * 2, "LFA 101: Test", "lfa")
        with self.assertRaises(AmbiguousEventError):
            matching_event(
                [{"event_id": 1, "event_name": "UFC Fight Night Seattle"}],
                "UFC Fight Night Seatle",
            )

    def test_different_frontend_and_importer_projects_are_rejected_before_writes(self):
        validate_project_urls("https://same.supabase.co", "https://same.supabase.co/")
        validate_project_urls("https://same.supabase.co", None)
        with self.assertRaisesRegex(ValueError, "different Supabase projects"):
            validate_project_urls("https://one.supabase.co", "https://two.supabase.co")

    def test_catalog_rename_requires_proof_and_different_ufc_numbers_cannot_match(self):
        importer = OfficialCatalogImporter.__new__(OfficialCatalogImporter)
        importer._events_near = lambda e: [
            {
                "event_id": 1,
                "event_date": "2026-10-12",
                "event_name": "UFC Old Main Event",
            }
        ]
        with self.assertRaises(AmbiguousEventError):
            importer._find_existing(
                {"date": date(2026, 10, 12), "name": "Unrelated Main Card"}
            )
        self.assertEqual(event_match_score("UFC 355 2026", "UFC 356 2026"), 0)

    def test_credentials_are_removed_from_reports_and_provider_urls(self):
        with patch.dict(os.environ, {"THE_ODDS_API_KEY": "secret-value"}):
            result = safe_error(
                "GET https://example.invalid?apiKey=secret-value&token=other Authorization: Bearer third"
            )
        self.assertNotIn("secret-value", result)
        self.assertNotIn("other", result)
        self.assertNotIn("third", result)

    def test_stale_one_sided_and_mixed_book_quotes_do_not_suppress_fallback(self):
        now = datetime.now(timezone.utc)
        base = {
            "events": [
                {
                    "event_id": 1,
                    "event_date": now.date().isoformat(),
                    "event_name": "UFC Card",
                    "promotions": {"name": "UFC"},
                }
            ],
            "fights": [
                {
                    "fight_id": 1,
                    "event_id": 1,
                    "fighter_a_id": 11,
                    "fighter_b_id": 12,
                    "fight_status": "scheduled",
                }
            ],
        }
        rows = [
            {
                "fight_id": 1,
                "fighter_id": 11,
                "sportsbook_key": "a",
                "american_odds": 100,
                "observed_at": now.isoformat(),
            },
            {
                "fight_id": 1,
                "fighter_id": 12,
                "sportsbook_key": "b",
                "american_odds": 100,
                "observed_at": now.isoformat(),
            },
        ]
        for quotes in (
            rows[:1],
            rows,
            [{**r, "observed_at": (now - timedelta(days=2)).isoformat()} for r in rows],
        ):
            self.assertEqual(
                audit_upcoming_coverage(
                    FakeSupabase({**base, "mma_odds_observations": quotes})
                )["odds"]["covered_fights"],
                0,
            )
        rows[1]["sportsbook_key"] = "a"
        self.assertEqual(
            audit_upcoming_coverage(
                FakeSupabase({**base, "mma_odds_observations": rows})
            )["odds"]["covered_fights"],
            1,
        )
