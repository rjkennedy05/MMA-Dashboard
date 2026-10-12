import unittest
from api.tests.fakes import rpc as fake_rpc

from api.providers.one_championship.importer import OneChampionshipImporter


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
            row = {
                "external_id_map_id": len(self.rows) + 1,
                **self.payload,
            }
            self.rows.append(row)
            return FakeResponse([row])
        if self.operation == "update":
            for row in matches:
                row.update(self.payload)
            return FakeResponse(matches)
        raise AssertionError(f"Unsupported operation: {self.operation}")


class FakeSupabase:
    rpc = fake_rpc

    def __init__(self, rows=None):
        self.external_ids = list(rows or [])

    def table(self, name):
        if name != "external_ids":
            raise AssertionError(f"Unexpected table: {name}")
        return FakeExternalIdsQuery(self.external_ids)


class FakeEventsQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def execute(self):
        return FakeResponse(
            [
                row
                for row in self.rows
                if all(row.get(column) == value for column, value in self.filters)
            ]
        )


class FakeEventSupabase:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        if name != "events":
            raise AssertionError(f"Unexpected table: {name}")
        return FakeEventsQuery(self.rows)


class OneChampionshipImporterMappingTests(unittest.TestCase):
    def make_importer(self, rows=None):
        importer = OneChampionshipImporter.__new__(OneChampionshipImporter)
        importer.supabase = FakeSupabase(rows)
        importer.source_id = 8
        return importer

    def test_inserts_mapping_when_internal_mapping_does_not_exist(self):
        importer = self.make_importer()

        importer._attach_mapping(
            "event", 37, "onefightnight46", "https://example.test/new"
        )

        self.assertEqual(len(importer.supabase.external_ids), 1)
        self.assertEqual(
            importer.supabase.external_ids[0]["external_id"],
            "onefightnight46",
        )

    def test_updates_existing_internal_mapping_when_external_id_changes(self):
        importer = self.make_importer(
            [
                {
                    "external_id_map_id": 91,
                    "entity_type": "event",
                    "internal_id": 37,
                    "source_id": 8,
                    "external_id": "one-fight-night-46-old",
                    "external_url": "https://example.test/old",
                }
            ]
        )

        importer._attach_mapping(
            "event", 37, "onefightnight46", "https://example.test/new"
        )

        self.assertEqual(len(importer.supabase.external_ids), 1)
        mapping = importer.supabase.external_ids[0]
        self.assertEqual(mapping["external_id_map_id"], 91)
        self.assertEqual(mapping["external_id"], "onefightnight46")
        self.assertEqual(mapping["external_url"], "https://example.test/new")

    def test_does_not_replace_mapping_from_another_source(self):
        importer = self.make_importer(
            [
                {
                    "external_id_map_id": 12,
                    "entity_type": "event",
                    "internal_id": 37,
                    "source_id": 7,
                    "external_id": "espn-event-id",
                }
            ]
        )

        importer._attach_mapping("event", 37, "onefightnight46")

        self.assertEqual(len(importer.supabase.external_ids), 2)
        self.assertEqual(
            {row["source_id"] for row in importer.supabase.external_ids},
            {7, 8},
        )


class OneChampionshipEventIdentityTests(unittest.TestCase):
    def make_importer(self, rows):
        importer = OneChampionshipImporter.__new__(OneChampionshipImporter)
        importer.supabase = FakeEventSupabase(rows)
        importer.promotion_id = 4
        return importer

    def test_matches_same_date_event_only_when_title_matches(self):
        importer = self.make_importer(
            [
                {
                    "event_id": 37,
                    "promotion_id": 4,
                    "event_date": "2026-08-14",
                    "event_name": "ONE Fight Night 46",
                }
            ]
        )

        self.assertEqual(
            importer._find_existing_event(
                "ONE Fight Night 46", "2026-08-14"
            ),
            37,
        )

    def test_does_not_merge_distinct_one_cards_on_the_same_date(self):
        importer = self.make_importer(
            [
                {
                    "event_id": 37,
                    "promotion_id": 4,
                    "event_date": "2026-08-14",
                    "event_name": "ONE Fight Night 46",
                }
            ]
        )

        self.assertIsNone(
            importer._find_existing_event(
                "ONE Friday Fights 166", "2026-08-14"
            )
        )


if __name__ == "__main__":
    unittest.main()
