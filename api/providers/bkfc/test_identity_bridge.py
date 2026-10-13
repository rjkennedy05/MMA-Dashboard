from copy import deepcopy
import unittest

from api.providers.bkfc.importer import BkfcImporter
from api.providers.bkfc.test_importer import FakeSupabase


class FighterPageIdentityTests(unittest.TestCase):
    def importer(self, conflicting=False):
        mappings = [{"entity_type": "fighter", "source_id": 10, "external_id": "maurice-morris",
                     "internal_id": 3029, "external_id_map_id": 1}]
        if conflicting:
            mappings.append({"entity_type": "fighter", "source_id": 10, "external_id": "results-uuid",
                             "internal_id": 3946, "external_id_map_id": 2})
        importer = BkfcImporter.__new__(BkfcImporter)
        importer.source_id = 10
        importer.supabase = FakeSupabase(rows=mappings, fighters=[
            {"fighter_id": 3029, "full_name": "Maurice Morris"},
            {"fighter_id": 3946, "full_name": "Maurice Morris"}])
        return importer

    def test_official_page_maps_new_results_uuid_without_merging_same_name_fighters(self):
        importer = self.importer()
        before = deepcopy(importer.supabase.fighters)
        fighter = {"external_id": "results-uuid", "name": "Maurice Morris",
                   "external_url": "https://www.bkfc.com/fighters/maurice-morris"}
        self.assertEqual(importer.get_or_create_fighter(fighter), 3029)
        self.assertEqual(importer.supabase.fighters, before)
        self.assertEqual(importer.get_or_create_fighter(fighter), 3029)

    def test_conflicting_established_page_and_uuid_mapping_refuses_the_fight(self):
        importer = self.importer(True)
        before = deepcopy(importer.supabase.external_ids)
        with self.assertRaisesRegex(RuntimeError, "identities disagree"):
            importer.get_or_create_fighter({"external_id": "results-uuid", "name": "Maurice Morris",
                                           "external_url": "https://www.bkfc.com/fighters/maurice-morris"})
        self.assertEqual(importer.supabase.external_ids, before)

    def test_untrusted_url_cannot_supply_a_page_identity(self):
        importer = self.importer()
        with self.assertRaisesRegex(RuntimeError, "Multiple fighters"):
            importer.get_or_create_fighter({"external_id": "results-uuid", "name": "Maurice Morris",
                                           "external_url": "https://other.example/fighters/maurice-morris"})
