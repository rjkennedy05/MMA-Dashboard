from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from api.sync.cards import card_day
from api.sync.readiness import CARD_FLAGS, finalize_readiness


class CardDisputeReadinessTests(unittest.TestCase):
    def args(self, **changes):
        return SimpleNamespace(mode="daily", requested_scope="all", skip_catalog=False,
                               skip_odds=True, dry_run=False,
                               **{flag: False for flag in CARD_FLAGS.values()}, **changes)

    def summary(self):
        return {"provider_runs": {**{key: {"status": "completed"} for key in CARD_FLAGS},
                                  "official_catalog": {"status": "completed"}},
                "quality_audit": {"status": "complete", "issues": []},
                "catalog_issues": [], "errors": [], "warnings": []}

    def test_bkfc_omissions_allow_publication_without_discarding_review_ids(self):
        summary = self.summary()
        issue = {"code": "CARD_SOURCE_OMISSION", "event_id": 42,
                 "event_name": "BKFC 95 NEWARK HERRING vs DODSON",
                 "event_date": "2026-10-17", "fight_ids": [9580, 9581]}
        summary["catalog_issues"] = [issue]
        summary["quality_audit"]["issues"] = [deepcopy(issue)]
        summary["checked_event_ids"] = [42, 42]
        finalize_readiness(summary, self.args())
        self.assertTrue(summary["publishable"])
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["publication_readiness"]["reasons"], [])
        self.assertEqual(summary["publication_readiness"]["disputes"], [issue])
        self.assertEqual(summary["publication_readiness"]["checked_event_ids"], [42])

    def test_distant_unconfirmed_cards_remain_in_review_metadata(self):
        summary = self.summary()
        summary["catalog_issues"] = [{"code": "CARD_SOURCE_EMPTY", "event_id": 60,
                                       "event_name": "ONE Future Card", "event_date": "2026-10-30"}]
        self.assertTrue(finalize_readiness(summary, self.args())["publishable"])
        self.assertEqual(len(summary["publication_readiness"]["disputes"]), 1)

    def test_fresh_successful_check_has_no_dispute_and_marks_the_checked_event(self):
        summary = self.summary()
        summary["checked_event_ids"] = [42]
        finalize_readiness(summary, self.args())
        self.assertEqual(summary["publication_readiness"]["disputes"], [])
        self.assertEqual(summary["publication_readiness"]["checked_event_ids"], [42])

    def test_incomplete_audits_or_all_failed_sources_prevent_publication(self):
        for target in ("all_sources", "audit"):
            with self.subTest(target=target):
                summary = self.summary()
                if target == "audit":
                    summary["quality_audit"]["status"] = "failed"
                else:
                    for key in CARD_FLAGS:
                        summary["provider_runs"][key]["status"] = "failed"
                self.assertFalse(finalize_readiness(summary, self.args())["publishable"])

    def test_one_failed_provider_flags_its_cards_and_allows_the_healthy_providers(self):
        summary = self.summary()
        summary["provider_runs"]["bkfc"]["status"] = "failed"
        summary["provider_runs"]["official_catalog"]["status"] = "failed"
        summary["quality_audit"]["cards"] = [{"event_id": 60, "event_name": "BKFC Card",
            "event_date": "2026-10-17", "promotion": "BKFC"}]
        self.assertTrue(finalize_readiness(summary, self.args())["publishable"])
        self.assertEqual(summary["publication_readiness"]["disputes"][0]["event_id"], 60)
        self.assertIn("Official event discovery", str(summary["publication_readiness"]["warnings"]))

    def test_one_rejected_card_can_post_the_retained_data_with_a_warning(self):
        summary = self.summary()
        summary["provider_runs"]["bkfc"]["status"] = "partial"
        summary["errors"] = [{"stage": "bkfc", "context": "BKFC 95 Newark",
                              "event_date": "2026-10-17", "message": "Conflicting source mapping"}]
        self.assertTrue(finalize_readiness(summary, self.args())["publishable"])
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["publication_readiness"]["disputes"][0]["code"], "CARD_IMPORT_REVIEW")

    def test_dry_runs_and_scoped_refreshes_cannot_publish(self):
        for mode in ("dry", "scoped"):
            args = self.args()
            if mode == "dry":
                args.dry_run = True
            else:
                args.requested_scope = "bkfc"
            self.assertFalse(finalize_readiness(self.summary(), args)["publishable"])

    def test_duplicate_fights_are_marked_even_without_a_date_field(self):
        summary = self.summary()
        summary["quality_audit"]["issues"] = [{"code": "DUPLICATE_FIGHT", "event_id": 42,
                                               "fight_ids": [1, 2]}]
        self.assertTrue(finalize_readiness(summary, self.args())["publishable"])
        self.assertEqual(summary["publication_readiness"]["disputes"][0]["fight_ids"], [1, 2])

    def test_card_warning_uses_the_central_calendar_day(self):
        self.assertEqual(card_day({"date": datetime(2026, 10, 18, tzinfo=timezone.utc)}), "2026-10-17")
        self.assertEqual(card_day({"date": "2026-10-18T00:00:00Z"}), "2026-10-17")
        self.assertEqual(card_day({"event_date": "2026-10-17", "date": "2026-10-18T00:00:00Z"}), "2026-10-17")


if __name__ == "__main__":
    unittest.main()
