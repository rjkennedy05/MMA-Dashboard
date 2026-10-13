from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
from postgrest import SyncPostgrestClient

from api.providers.atomic import AtomicImportClient
from api.providers.espn_mma import normalizer as shared
from api.providers.espn_mma.test_importer import FakeSupabase
from api.providers.fight_identity import FightIdentityError
from api.providers.persistence import find_identity
from api.providers.pfl_official.client import OfficialPflClient
from api.providers.pfl_official.importer import OfficialPflImporter
from api.providers.pfl_official.normalizer import OfficialPflCardError, card_metadata, normalize_card
from api.providers.pfl_official.fallback import sync_pfl_cards
from api.sync.cards import import_card
from api.sync.readiness import CARD_FLAGS, finalize_readiness

FIXTURES = Path(__file__).with_name("fixtures")
ENTRY = {"external_id": "pfl:pfl-morocco", "external_url": "https://pflmma.com/event/pfl-morocco",
         "name": "PFL Africa Morocco", "date": "2026-10-10", "promotion_key": "pfl", "event_id": 5}
NOW = datetime(2026, 10, 12, 12, tzinfo=ZoneInfo("America/Chicago"))


def fixtures():
    html = (FIXTURES / "morocco_card_20261012.html").read_text()
    payload = json.loads((FIXTURES / "morocco_results_20261012.json").read_text())
    return html, card_metadata(html, ENTRY), payload


def database():
    return FakeSupabase([], {"data_sources": [{"source_id": 1, "name": "ESPN MMA"},
        {"source_id": 77, "name": "PFL Official Event Catalog"}],
        "promotions": [{"promotion_id": 2, "name": "PFL"}], "weight_classes": [],
        "events": [{"event_id": 5, "promotion_id": 2, "event_date": "2026-10-10", "event_name": ENTRY["name"]}],
        "external_ids": [{"entity_type": "event", "source_id": 77,
            "external_id": ENTRY["external_id"], "internal_id": 5}]})


class OfficialCardTests(unittest.TestCase):
    def test_live_source_fixture_verifies_all_results_and_keeps_the_catalog_day(self):
        _, metadata, payload = fixtures()
        event, fights = normalize_card(ENTRY, metadata, payload)
        self.assertEqual(event["event_date"], "2026-10-10")
        self.assertNotIn("event_start_time", event)  # Midnight is only a date placeholder.
        self.assertEqual(event["event_status"], "completed")
        self.assertEqual(len(fights), 11)
        self.assertEqual([shared.normalized_status(f) for f in fights].count("no_contest"), 1)
        self.assertEqual(shared.winner_external_id(fights[0]), "pfl-fighter:975")
        self.assertEqual(shared.finish_round(fights[0]), 1)
        self.assertEqual(shared.finish_time_seconds(fights[0]), 246)
        self.assertIsNone(shared.winner_external_id(fights[8]))

    def test_partial_card_and_duplicate_matchups_are_rejected_before_import(self):
        _, metadata, payload = fixtures()
        for bad in (payload[:-1], payload + [payload[0]], []):
            with self.subTest(length=len(bad)), self.assertRaises(OfficialPflCardError):
                normalize_card(ENTRY, metadata, bad)

    def test_winner_must_be_a_participant_and_agree_with_the_corner(self):
        _, metadata, payload = fixtures()
        for winner, corner in ((999999, "red"), (975, "blue"), (None, "red")):
            bad = deepcopy(payload)
            bad[0].update(WinnerId=winner, WinnerResult=corner)
            with self.subTest(winner=winner, corner=corner), self.assertRaises(OfficialPflCardError):
                normalize_card(ENTRY, metadata, bad)

    def test_unknown_status_or_conflicting_no_contest_keeps_the_card_unverified(self):
        _, metadata, payload = fixtures()
        for values in ({"Status": "mystery"}, {"OverrideStatus": "no_contest"},
                       {"OverrideStatus": "mystery"}, {"RoundTime": "R1 5:99"}):
            bad = deepcopy(payload)
            bad[0].update(values)
            with self.subTest(values=values), self.assertRaises(OfficialPflCardError):
                normalize_card(ENTRY, metadata, bad)

    def test_date_alone_cannot_complete_an_unfinished_card(self):
        _, metadata, payload = fixtures()
        payload[0].update(Status="In Progress", WinnerId=None, WinnerResult=None,
                          WinBy=None, RoundTime=None)
        event, fights = normalize_card(ENTRY, metadata, payload)
        self.assertEqual(event["event_status"], "live")
        self.assertEqual(shared.normalized_status(fights[0]), "in_progress")
        self.assertIsNone(shared.winner_external_id(fights[0]))

    def test_all_explicitly_cancelled_bouts_mark_the_event_cancelled(self):
        _, metadata, payload = fixtures()
        for row in payload:
            row.update(Status="Cancelled", OverrideStatus=None, WinnerId=None,
                       WinnerResult=None, WinBy=None, RoundTime=None)
        event, fights = normalize_card(ENTRY, metadata, payload)
        self.assertEqual(event["event_status"], "cancelled")
        self.assertEqual({shared.normalized_status(f) for f in fights}, {"cancelled"})

    def test_card_order_changes_do_not_change_official_fight_identities(self):
        _, metadata, payload = fixtures()
        _, original = normalize_card(ENTRY, metadata, payload)
        payload[0]["FightNumber"], payload[1]["FightNumber"] = 2, 1
        _, reordered = normalize_card(ENTRY, metadata, payload)
        self.assertEqual({f["id"] for f in original}, {f["id"] for f in reordered})

    def test_wrong_event_date_or_missing_declared_card_is_rejected(self):
        html, _, _ = fixtures()
        for bad in (html.replace("2026-10-10", "2025-10-10"), "<h1>PFL Africa Morocco</h1>"):
            with self.assertRaises(OfficialPflCardError):
                card_metadata(bad, ENTRY)

    def test_import_reuses_catalog_identity_and_records_official_provenance(self):
        raw = database()
        _, metadata, payload = fixtures()
        event, fights = normalize_card(ENTRY, metadata, payload)
        importer = OfficialPflImporter(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(saved["event_id"], 5)
        self.assertEqual(len(raw.rows["events"]), 1)
        self.assertEqual(len(raw.rows["fights"]), 11)
        self.assertEqual(len(raw.rows["fighters"]), 22)
        self.assertEqual(len(results), 11)
        self.assertEqual({r["source_id"] for r in raw.rows["external_ids"]}, {77})
        self.assertNotIn("event_start_time", raw.rows["events"][0])
        first = [(r["fight_id"], r["fighter_a_id"], r["fighter_b_id"]) for r in raw.rows["fights"]]
        raw.rows["bet_legs"].append({"leg_id": 1, "fight_id": first[0][0], "selection": "A"})
        original_bet = deepcopy(raw.rows["bet_legs"])
        fights[0]["competitors"].reverse()
        for index, slot in enumerate(fights[0]["competitors"], 1):
            slot["order"] = index
        import_card(importer, event, fights)
        self.assertEqual(first, [(r["fight_id"], r["fighter_a_id"], r["fighter_b_id"]) for r in raw.rows["fights"]])
        self.assertEqual(raw.rows["bet_legs"], original_bet)


class SavedCardIdentityTests(unittest.TestCase):
    def saved_card(self, duplicates=False):
        raw = database()
        _, metadata, payload = fixtures()
        event, fights = normalize_card(ENTRY, metadata, payload)
        for index, fight in enumerate(fights):
            fighters = shared.fighters(fight)
            ids = (5670, 5673) if index == 2 else (10000 + index * 2, 10001 + index * 2)
            names = [fighter["name"] for fighter in fighters]
            if index == 2:
                names = ["Shido Boris Esperanca", "Peace Nguphane"]
            raw.rows["fighters"].extend({"fighter_id": fid, "full_name": name}
                                        for fid, name in zip(ids, names))
            raw.rows["fights"].append({"fight_id": 9538 + index, "event_id": 5,
                "fighter_a_id": ids[0], "fighter_b_id": ids[1], "fight_status": "scheduled",
                "fighter_a": {"full_name": names[0]}, "fighter_b": {"full_name": names[1]}})
        if duplicates:
            raw.rows["fighters"].extend([
                {"fighter_id": 6000, "full_name": "Shido Boris Esperança"},
                {"fighter_id": 6001, "full_name": "Peace Nguphane"}])
        raw.rows["fight_research"] = [{"fight_id": 9540, "bet_side": "fighter_a",
                                      "assistant_pick": "fighter_b", "confidence": 4}]
        raw.rows["bet_legs"] = [{"leg_id": 1, "fight_id": 9540, "bet_side": "fighter_b"}]
        return raw, event, fights

    def sdk_importer(self, raw):
        """Run the real SDK, pagination and batch overlay over isolated records."""
        commits = []

        def transport(request):
            if "/rpc/" in request.url.path:
                name = request.url.path.rsplit("/", 1)[-1]
                args = json.loads(request.content)
                if name in {"mma_apply_import_batch", "mma_apply_import_batch_resilient"}:
                    commits.append(deepcopy(args))
                return httpx.Response(200, json=raw.rpc(name, args).execute().data)
            table = request.url.path.rsplit("/", 1)[-1]
            rows = deepcopy(raw.rows[table])
            params = request.url.params
            for key, value in params.multi_items():
                if value.startswith("eq."):
                    rows = [r for r in rows if str(r.get(key)) == value[3:]]
            if table == "fights":
                fighters = {r["fighter_id"]: r for r in raw.rows["fighters"]}
                for row in rows:
                    for side in ("fighter_a", "fighter_b"):
                        row[side] = {"full_name": fighters[row[side + "_id"]]["full_name"]}
            order = params.get("order")
            if order:
                key = order.split(",")[-1].split(".")[0]
                rows.sort(key=lambda r: r[key])
            start = int(params.get("offset", "0"))
            limit = min(int(params.get("limit", "500")), 2)  # Exercise server row caps.
            return httpx.Response(200, json=rows[start:start + limit])

        http = httpx.Client(transport=httpx.MockTransport(transport))
        self.addCleanup(http.close)
        client = SyncPostgrestClient("https://example.invalid", http_client=http)
        importer = OfficialPflImporter(AtomicImportClient(client))
        self.addCleanup(importer.clear_lookup_caches)
        return importer, commits

    def test_full_existing_card_attaches_source_ids_without_changing_saved_fighter_names(self):
        raw, event, fights = self.saved_card()
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(len(commits), 1)
        self.assertEqual(saved["unconfirmed_omissions"], [])
        self.assertEqual(len(results), 11)
        self.assertEqual(raw.rows["fighters"], before["fighters"])
        self.assertEqual(raw.rows["fight_research"], before["fight_research"])
        self.assertEqual(raw.rows["bet_legs"], before["bet_legs"])
        expected = [(r["fight_id"], r["fighter_a_id"], r["fighter_b_id"]) for r in before["fights"]]
        self.assertEqual(expected, [(r["fight_id"], r["fighter_a_id"], r["fighter_b_id"]) for r in raw.rows["fights"]])
        links = {r["external_id"]: r["internal_id"] for r in raw.rows["external_ids"]}
        self.assertEqual(links["pfl-fighter:866"], 5670)
        self.assertEqual(links["pfl-fighter:1160"], 5673)
        self.assertEqual(links["pfl-fight:pfl-morocco:10851"], 9540)
        self.assertTrue(all(r["fight_status"] in {"completed", "no_contest"} for r in raw.rows["fights"]))

    def test_accented_duplicates_reuse_the_saved_pair_after_reversal_and_repeat_imports(self):
        raw, event, fights = self.saved_card(duplicates=True)
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        fights[2]["competitors"].reverse()
        for index, slot in enumerate(fights[2]["competitors"], 1):
            slot["order"] = index
        for _ in range(2):
            import_card(importer, event, fights)
        self.assertEqual(len(commits), 2)
        self.assertEqual(raw.rows["fighters"], before["fighters"])
        self.assertEqual(raw.rows["fight_research"], before["fight_research"])
        self.assertEqual(raw.rows["bet_legs"], before["bet_legs"])
        bout = next(r for r in raw.rows["fights"] if r["fight_id"] == 9540)
        self.assertEqual((bout["fighter_a_id"], bout["fighter_b_id"]), (5670, 5673))
        self.assertEqual(len(raw.rows["fights"]), 11)

    def test_conflicting_fighter_mapping_preserves_that_bout_and_updates_the_rest(self):
        raw, event, fights = self.saved_card(duplicates=True)
        raw.rows["external_ids"].append({"entity_type": "fighter", "source_id": 77,
                                        "external_id": "pfl-fighter:1160", "internal_id": 6001})
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(len(commits), 1)
        self.assertEqual(len(saved["fight_reviews"]), 1)
        self.assertRegex(saved["fight_reviews"][0]["message"], "maps to #6001.*uses #5673")
        self.assertEqual(results[2]["status"], "review")
        self.assertEqual(sum(r["status"] in {"updated", "imported"} for r in results), 10)
        self.assertEqual(next(r for r in raw.rows["fights"] if r["fight_id"] == 9540),
                         next(r for r in before["fights"] if r["fight_id"] == 9540))
        self.assertEqual(raw.rows["fighters"], before["fighters"])
        self.assertEqual(raw.rows["fight_research"], before["fight_research"])
        self.assertEqual(raw.rows["bet_legs"], before["bet_legs"])
        for link in before["external_ids"]:
            self.assertEqual(find_identity(raw, link["entity_type"], link["source_id"],
                                           link["external_id"])["internal_id"], link["internal_id"])
        self.assertFalse(any(op.get("bout_group") == "3" for op in commits[0]["p_operations"]))

    def test_single_fight_checks_both_source_mappings_before_attaching_either(self):
        raw, _, fights = self.saved_card(duplicates=True)
        raw.rows["external_ids"].append({"entity_type": "fighter", "source_id": 77,
                                        "external_id": "pfl-fighter:1160", "internal_id": 6001})
        before = deepcopy(raw.rows)
        importer = OfficialPflImporter(raw)
        self.addCleanup(importer.clear_lookup_caches)
        with self.assertRaisesRegex(FightIdentityError, "maps to #6001.*uses #5673"):
            importer.import_fight(5, fights[2], 3)
        self.assertEqual(raw.rows, before)

    def test_new_card_still_creates_and_commits_all_fighter_identities(self):
        raw = database()
        _, metadata, payload = fixtures()
        event, fights = normalize_card(ENTRY, metadata, payload)
        importer, commits = self.sdk_importer(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(len(commits), 1)
        self.assertEqual(saved["unconfirmed_omissions"], [])
        self.assertEqual(len(results), 11)
        self.assertEqual(len(raw.rows["fighters"]), 22)
        self.assertEqual(len(raw.rows["fights"]), 11)
        self.assertTrue(all(r["fight_id"] > 0 for r in results))
        self.assertTrue(all(r["internal_id"] > 0 for r in raw.rows["external_ids"]))

    def test_conflict_on_the_last_fight_keeps_the_other_ten_results(self):
        raw, event, fights = self.saved_card()
        fighter = shared.fighters(fights[-1])[1]
        raw.rows["fighters"].append({"fighter_id": 13000, "full_name": fighter["name"]})
        raw.rows["external_ids"].append({"entity_type": "fighter", "source_id": 77,
                                        "external_id": fighter["external_id"], "internal_id": 13000})
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(len(commits), 1)
        self.assertEqual(len(saved["fight_reviews"]), 1)
        self.assertRegex(saved["fight_reviews"][0]["message"], "fighter source mapping")
        self.assertEqual(results[10]["status"], "review")
        self.assertEqual(sum(r["status"] in {"updated", "imported"} for r in results), 10)
        self.assertEqual(next(r for r in raw.rows["fights"] if r["fight_id"] == 9548),
                         next(r for r in before["fights"] if r["fight_id"] == 9548))
        self.assertEqual(raw.rows["fighters"], before["fighters"])
        self.assertEqual(raw.rows["fight_research"], before["fight_research"])
        self.assertEqual(raw.rows["bet_legs"], before["bet_legs"])
        for link in before["external_ids"]:
            self.assertEqual(find_identity(raw, link["entity_type"], link["source_id"],
                                           link["external_id"])["internal_id"], link["internal_id"])
        self.assertFalse(any(op.get("bout_group") == "11" for op in commits[0]["p_operations"]))

    def test_two_different_saved_pairs_with_the_same_names_require_review(self):
        raw, event, fights = self.saved_card(duplicates=True)
        raw.rows["fights"].append({"fight_id": 13000, "event_id": 5,
            "fighter_a_id": 6000, "fighter_b_id": 6001, "fight_status": "scheduled"})
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(len(commits), 1)
        self.assertEqual(len(saved["fight_reviews"]), 1)
        self.assertRegex(saved["fight_reviews"][0]["message"], "multiple saved fighter pairs")
        self.assertEqual(results[2]["status"], "review")
        self.assertEqual(sum(r["status"] in {"updated", "imported"} for r in results), 10)
        self.assertEqual(next(r for r in raw.rows["fights"] if r["fight_id"] == 9540),
                         next(r for r in before["fights"] if r["fight_id"] == 9540))
        self.assertEqual(raw.rows["fighters"], before["fighters"])
        self.assertEqual(raw.rows["fight_research"], before["fight_research"])
        self.assertEqual(raw.rows["bet_legs"], before["bet_legs"])
        for link in before["external_ids"]:
            self.assertEqual(find_identity(raw, link["entity_type"], link["source_id"],
                                           link["external_id"])["internal_id"], link["internal_id"])
        self.assertFalse(any(op.get("bout_group") == "3" for op in commits[0]["p_operations"]))

    def test_a_changed_opponent_cannot_reuse_a_mapped_historical_fight(self):
        raw, event, fights = self.saved_card()
        raw.rows["external_ids"].append({"entity_type": "fight", "source_id": 77,
            "external_id": "pfl-fight:pfl-morocco:10851", "internal_id": 9540})
        fights[2]["competitors"][1]["athlete"].update(id="pfl-fighter:999999", displayName="Replacement Fighter")
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(len(commits), 1)
        self.assertEqual(len(saved["fight_reviews"]), 1)
        self.assertRegex(saved["fight_reviews"][0]["message"], "different stored participants")
        self.assertEqual(results[2]["status"], "review")
        self.assertEqual(sum(r["status"] in {"updated", "imported"} for r in results), 10)
        self.assertEqual(next(r for r in raw.rows["fights"] if r["fight_id"] == 9540),
                         next(r for r in before["fights"] if r["fight_id"] == 9540))
        self.assertEqual(raw.rows["fighters"], before["fighters"])
        self.assertEqual(raw.rows["fight_research"], before["fight_research"])
        self.assertEqual(raw.rows["bet_legs"], before["bet_legs"])
        for link in before["external_ids"]:
            self.assertEqual(find_identity(raw, link["entity_type"], link["source_id"],
                                           link["external_id"])["internal_id"], link["internal_id"])
        self.assertFalse(any(op.get("bout_group") == "3" for op in commits[0]["p_operations"]))

    def test_a_conflicting_fight_source_mapping_is_not_redirected(self):
        raw, event, fights = self.saved_card()
        raw.rows["external_ids"].append({"entity_type": "fight", "source_id": 77,
            "external_id": "pfl-fight:pfl-morocco:10851", "internal_id": 9538})
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        saved, results = import_card(importer, event, fights)
        self.assertEqual(len(commits), 1)
        self.assertEqual(len(saved["fight_reviews"]), 1)
        self.assertRegex(saved["fight_reviews"][0]["message"], "fight source ID points to another")
        self.assertEqual(results[2]["status"], "review")
        self.assertEqual(sum(r["status"] in {"updated", "imported"} for r in results), 10)
        self.assertEqual(next(r for r in raw.rows["fights"] if r["fight_id"] == 9540),
                         next(r for r in before["fights"] if r["fight_id"] == 9540))
        self.assertEqual(raw.rows["fighters"], before["fighters"])
        self.assertEqual(raw.rows["fight_research"], before["fight_research"])
        self.assertEqual(raw.rows["bet_legs"], before["bet_legs"])
        for link in before["external_ids"]:
            self.assertEqual(find_identity(raw, link["entity_type"], link["source_id"],
                                           link["external_id"])["internal_id"], link["internal_id"])
        self.assertFalse(any(op.get("bout_group") == "3" for op in commits[0]["p_operations"]))

    def test_dry_run_does_not_attach_source_ids_or_change_saved_data(self):
        raw, event, fights = self.saved_card(duplicates=True)
        before = deepcopy(raw.rows)
        importer, commits = self.sdk_importer(raw)
        import_card(importer, event, fights, dry_run=True)
        self.assertEqual(commits, [])
        self.assertEqual(raw.rows, before)


class ClientTests(unittest.TestCase):
    def session(self, html=None):
        html = html or fixtures()[0]
        session = unittest.mock.MagicMock()
        session.get.return_value = SimpleNamespace(text=html, url=ENTRY["external_url"],
                                                   raise_for_status=lambda: None)
        session.post.return_value = SimpleNamespace(status_code=200, json=lambda: fixtures()[2],
                                                    raise_for_status=lambda: None)
        return session

    def test_public_query_uses_page_session_token_and_the_matching_post_endpoint(self):
        session = self.session()
        client = OfficialPflClient(session=session)
        event, fights = client.get_card(ENTRY)
        self.assertEqual(len(fights), 11)
        self.assertEqual(client.request_count, 2)
        self.assertEqual(session.post.call_args.args[0], "https://pflmma.com/smt/v2/pfl-morocco")
        self.assertEqual(session.post.call_args.kwargs["headers"]["X-CSRF-TOKEN"], "fixture-token")
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])

    def test_other_hosts_or_event_endpoints_are_not_queried(self):
        html = fixtures()[0]
        for endpoint in ("https://elsewhere.example/smt/v2/pfl-morocco",
                         "https://pflmma.com/smt/v2/dubai"):
            session = self.session(html.replace("https://pflmma.com/smt/v2/pfl-morocco", endpoint))
            with self.assertRaises(OfficialPflCardError):
                OfficialPflClient(session=session).get_card(ENTRY)
            session.post.assert_not_called()

    def test_missing_page_token_or_redirect_keeps_card_unverified(self):
        session = self.session(fixtures()[0].replace('value="fixture-token"', 'value=""'))
        with self.assertRaises(OfficialPflCardError):
            OfficialPflClient(session=session).get_card(ENTRY)
        session.post.assert_not_called()
        session = self.session()
        session.post.return_value.status_code = 302
        with self.assertRaises(OfficialPflCardError):
            OfficialPflClient(session=session).get_card(ENTRY)


class FallbackFlowTests(unittest.TestCase):
    def setup_flow(self):
        args = SimpleNamespace(past_days=2, future_days=21, dry_run=False,
                               mode="daily", requested_scope="all", skip_catalog=False, skip_odds=True,
                               **{flag: False for flag in CARD_FLAGS.values()})
        summary = {"provider_runs": {key: {"status": "completed"} for key in CARD_FLAGS},
                   "providers": {"pfl": "automatic"}, "catalog_issues": [], "warnings": [], "errors": [],
                   "events_seen": 0, "events_in_window": 0, "fights_seen": 0,
                   "events_imported": 0, "events_updated": 0, "fights_imported": 0, "fights_updated": 0,
                   "official_results_found": 0, "quality_audit": {"status": "complete", "issues": []}}
        summary["provider_runs"]["official_catalog"] = {"status": "completed", "entries": [ENTRY]}
        return args, summary, database()

    def run_flow(self, official_error=False):
        args, summary, raw = self.setup_flow()
        with patch("api.providers.pfl_official.fallback.EspnMmaClient") as espn, \
             patch("api.providers.pfl_official.fallback.OfficialPflClient") as official, \
             patch("api.providers.pfl_official.fallback.datetime") as clock:
            espn.return_value.get_events_in_window.return_value = []
            espn.return_value._get_core_events.return_value = []
            espn.return_value.request_count = 2
            official.return_value.request_count = 2
            clock.now.return_value = NOW
            if official_error:
                official.return_value.get_card.side_effect = OfficialPflCardError("Card incomplete")
            else:
                _, metadata, payload = fixtures()
                official.return_value.get_card.return_value = normalize_card(ENTRY, metadata, payload)
            sync_pfl_cards(args, summary, raw, lambda *a: True, lambda *a: None)
        summary["quality_audit"]["issues"] = list(summary["catalog_issues"])
        finalize_readiness(summary, args)
        return summary, raw

    def test_missing_espn_card_is_verified_and_imported_before_publication_is_ready(self):
        summary, raw = self.run_flow()
        self.assertTrue(summary["publishable"])
        self.assertEqual(summary["catalog_issues"], [])
        self.assertEqual(len(raw.rows["fights"]), 11)
        self.assertEqual(summary["official_results_found"], 11)
        self.assertEqual(summary["provider_runs"]["espn_mma"]["source"], "official_pfl_fallback")

    def test_unverified_card_retains_source_gap_and_posts_with_review_metadata(self):
        summary, raw = self.run_flow(official_error=True)
        self.assertTrue(summary["publishable"])
        self.assertEqual(summary["catalog_issues"][0]["code"], "DETAIL_SOURCE_GAP")
        self.assertEqual(raw.rows["fights"], [])
        self.assertEqual(len(raw.rows["events"]), 1)
        self.assertIn("CARD_IMPORT_REVIEW", {d["code"] for d in summary["publication_readiness"]["disputes"]})

    def test_source_failure_cannot_be_treated_as_a_quiet_catalog(self):
        args, summary, raw = self.setup_flow()
        summary["provider_runs"]["official_catalog"].update(status="failed", entries=[])
        with patch("api.providers.pfl_official.fallback.EspnMmaClient") as espn, \
             patch("api.providers.pfl_official.fallback.OfficialPflClient") as official:
            espn.return_value.get_events_in_window.return_value = []
            espn.return_value.request_count = 1
            sync_pfl_cards(args, summary, raw, lambda *a: True, lambda *a: None)
            official.assert_not_called()
        self.assertEqual(summary["provider_runs"]["espn_mma"]["status"], "failed")

    def native_flow(self, with_morocco, native_error=False):
        args, summary, raw = self.setup_flow()
        chicago = {"external_id": "pfl:2026-chicago2", "external_url": "https://pflmma.com/event/2026-chicago2",
                   "name": "PFL Chicago 2", "date": "2026-10-16", "promotion_key": "pfl"}
        summary["provider_runs"]["official_catalog"]["entries"] = [chicago, ENTRY] if with_morocco else [chicago]
        fight = {"id": "native-bout", "competitors": [
            {"order": 1, "athlete": {"id": "native-a", "displayName": "Native Fighter A"}},
            {"order": 2, "athlete": {"id": "native-b", "displayName": "Native Fighter B"}}],
            "status": {"type": {"name": "scheduled", "completed": False, "state": "pre"}}}
        event = {"id": "native-chicago", "name": "PFL Chicago: Carmouche vs. Bishop 2",
                 "date": "2026-10-16T23:00:00Z", "competitions": [fight]}
        with patch("api.providers.pfl_official.fallback.EspnMmaClient") as espn, \
             patch("api.providers.pfl_official.fallback.OfficialPflClient") as official, \
             patch("api.providers.pfl_official.fallback.datetime") as clock:
            espn.return_value.get_events_in_window.return_value = [event]
            espn.return_value._get_core_events.return_value = [event]
            espn.return_value.get_fightcenter.return_value = {}
            if native_error:
                espn.return_value.get_fightcenter.side_effect = RuntimeError("Native card unavailable")
            espn.return_value.request_count = 3
            espn.return_value.event_source = "site_scoreboard"
            espn.return_value.fightcenter_fallbacks = 0
            clock.now.return_value = NOW
            _, metadata, payload = fixtures()
            official.return_value.get_card.return_value = normalize_card(ENTRY, metadata, payload)
            official.return_value.request_count = 2
            sync_pfl_cards(args, summary, raw, lambda *a: True, lambda *a: None)
            queried = official.return_value.get_card.call_args_list
            created = official.call_count
        summary["quality_audit"]["issues"] = list(summary["catalog_issues"])
        finalize_readiness(summary, args)
        return summary, raw, created, queried

    def test_only_missing_listing_uses_the_official_feed_alongside_native_cards(self):
        summary, raw, created, queried = self.native_flow(with_morocco=True)
        self.assertTrue(summary["publishable"])
        self.assertEqual(len(raw.rows["fights"]), 12)
        self.assertEqual(len(queried), 1)
        self.assertEqual(queried[0].args[0]["name"], "PFL Africa Morocco")

    def test_matching_native_card_does_not_trigger_the_official_fallback(self):
        summary, raw, created, queried = self.native_flow(with_morocco=False)
        self.assertEqual(created, 0)
        self.assertEqual(len(raw.rows["fights"]), 1)
        self.assertTrue(summary["publishable"])

    def test_official_success_cannot_hide_a_failure_on_another_native_card(self):
        summary, raw, created, queried = self.native_flow(with_morocco=True, native_error=True)
        self.assertTrue(summary["publishable"])
        self.assertEqual(summary["provider_runs"]["espn_mma"]["status"], "partial")
        self.assertEqual(len(raw.rows["fights"]), 11)


if __name__ == "__main__":
    unittest.main()
