import unittest

from api.providers.lfa.importer import LfaImporter


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
    def __init__(self, rows=None):
        self.external_ids = list(rows or [])

    def table(self, name):
        if name != "external_ids":
            raise AssertionError(f"Unexpected table: {name}")
        return FakeExternalIdsQuery(self.external_ids)


class LfaImporterMappingTests(unittest.TestCase):
    def make_importer(self, rows=None):
        importer = LfaImporter.__new__(LfaImporter)
        importer.supabase = FakeSupabase(rows)
        importer.source_id = 9
        return importer

    def test_inserts_fresh_mapping(self):
        importer = self.make_importer()
        importer._attach_mapping("event", 51, "lfa-239")
        self.assertEqual(importer.supabase.external_ids[0]["external_id"], "lfa-239")

    def test_updates_mapping_when_external_value_changes(self):
        importer = self.make_importer(
            [{
                "external_id_map_id": 92,
                "entity_type": "event",
                "internal_id": 51,
                "source_id": 9,
                "external_id": "old-lfa-239",
            }]
        )
        importer._attach_mapping("event", 51, "lfa-239")
        self.assertEqual(len(importer.supabase.external_ids), 1)
        self.assertEqual(importer.supabase.external_ids[0]["external_id"], "lfa-239")

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
        importer._attach_mapping("event", 51, "lfa-239")
        self.assertEqual(len(importer.supabase.external_ids), 2)
        self.assertEqual({row["source_id"] for row in importer.supabase.external_ids}, {8, 9})


if __name__ == "__main__":
    unittest.main()
