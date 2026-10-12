import unittest
from api.tests.fakes import rpc as fake_rpc

from api.providers.bkfc.importer import BkfcImporter


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeExternalIdsQuery:
    def __init__(self, rows):
        self.rows = rows
        self.operation = "select"
        self.payload = None
        self.filters = []

    def select(self, _columns):
        self.operation = "select"
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _count):
        return self

    def execute(self):
        matches = [
            row
            for row in self.rows
            if all(row.get(column) == value for column, value in self.filters)
        ]
        if self.operation == "select":
            return FakeResponse(matches)
        if self.operation == "insert":
            row = {"external_id_map_id": len(self.rows) + 1, **self.payload}
            self.rows.append(row)
            return FakeResponse([row])
        if self.operation == "update":
            for row in matches:
                row.update(self.payload)
            return FakeResponse(matches)
        raise AssertionError(f"Unsupported operation: {self.operation}")


class FakeSupabase:
    rpc = fake_rpc

    def __init__(self, rows=None, fighters=None):
        self.external_ids = list(rows or [])
        self.fighters = list(fighters or [])

    def table(self, name):
        if name == "external_ids":
            return FakeExternalIdsQuery(self.external_ids)
        if name == "fighters":
            return FakeExternalIdsQuery(self.fighters)
        raise AssertionError(f"Unexpected table: {name}")


class BkfcImporterMappingTests(unittest.TestCase):
    def make_importer(self, rows=None):
        importer = BkfcImporter.__new__(BkfcImporter)
        importer.supabase = FakeSupabase(rows)
        importer.source_id = 10
        return importer

    def test_inserts_fresh_mapping(self):
        importer = self.make_importer()
        importer._attach_mapping("event", 51, "bkfc-92")
        self.assertEqual(importer.supabase.external_ids[0]["external_id"], "bkfc-92")

    def test_updates_mapping_when_external_value_changes(self):
        importer = self.make_importer(
            [{
                "external_id_map_id": 92,
                "entity_type": "event",
                "internal_id": 51,
                "source_id": 10,
                "external_id": "old-bkfc-92",
            }]
        )
        importer._attach_mapping("event", 51, "bkfc-92")
        self.assertEqual(len(importer.supabase.external_ids), 1)
        self.assertEqual(importer.supabase.external_ids[0]["external_id"], "bkfc-92")

    def test_preserves_other_provider_mapping(self):
        importer = self.make_importer(
            [{
                "external_id_map_id": 12,
                "entity_type": "event",
                "internal_id": 51,
                "source_id": 8,
                "external_id": "other-source-id",
            }]
        )
        importer._attach_mapping("event", 51, "bkfc-92")
        self.assertEqual(len(importer.supabase.external_ids), 2)
        self.assertEqual(
            {row["source_id"] for row in importer.supabase.external_ids},
            {8, 10},
        )

    def test_repairs_placeholder_name_for_mapped_fighter(self):
        importer = self.make_importer(
            [{
                "external_id_map_id": 21,
                "entity_type": "fighter",
                "internal_id": 7,
                "source_id": 10,
                "external_id": "carlos-trinidad",
            }]
        )
        importer.supabase.fighters.append(
            {
                "fighter_id": 7,
                "first_name": "Win",
                "last_name": "Loss Draw No Contest",
                "full_name": "Win Loss Draw No Contest",
            }
        )
        fighter_id = importer.get_or_create_fighter(
            {
                "external_id": "carlos-trinidad",
                "name": "Carlos Trinidad",
            }
        )
        self.assertEqual(fighter_id, 7)
        self.assertEqual(
            importer.supabase.fighters[0]["full_name"],
            "Carlos Trinidad",
        )

    def test_preserves_valid_name_for_mapped_fighter(self):
        importer = self.make_importer(
            [{
                "external_id_map_id": 22,
                "entity_type": "fighter",
                "internal_id": 8,
                "source_id": 10,
                "external_id": "lewis-garside",
            }]
        )
        importer.supabase.fighters.append(
            {
                "fighter_id": 8,
                "first_name": "Lewis",
                "last_name": "Garside",
                "full_name": "Lewis Garside",
            }
        )
        importer.get_or_create_fighter(
            {
                "external_id": "lewis-garside",
                "name": "Lewis Garside",
            }
        )
        self.assertEqual(
            importer.supabase.fighters[0]["full_name"],
            "Lewis Garside",
        )


if __name__ == "__main__":
    unittest.main()
