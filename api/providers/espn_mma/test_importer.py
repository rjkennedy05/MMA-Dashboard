from __future__ import annotations

import unittest
from copy import deepcopy
from api.tests.fakes import rpc as fake_rpc

try:
    from .importer import UfcImporter, fighter_name_key
except ImportError:
    from api.providers.espn_mma.importer import UfcImporter, fighter_name_key


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, table_name, rows):
        self.table_name = table_name
        self.rows = rows
        self.filters = []
        self.payload = None
        self.operation = "select"

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _count):
        return self

    def insert(self, payload):
        self.operation = "insert"
        self.payload = dict(payload)
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = dict(payload)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def execute(self):
        if self.operation == "insert":
            row = dict(self.payload)
            id_columns = {
                "fighters": "fighter_id",
                "fights": "fight_id",
                "external_ids": "external_id_map_id",
                "fight_research": "research_id",
                "odds": "odds_id",
                "bet_legs": "leg_id",
            }
            id_column = id_columns.get(self.table_name)
            if id_column and id_column not in row:
                row["fighter_id"] = max(
                    [int(item.get(id_column) or 0) for item in self.rows] or [0]
                ) + 1
                if id_column != "fighter_id":
                    row[id_column] = row.pop("fighter_id")
            self.rows.append(row)
            return FakeResponse([row])
        if self.operation == "update":
            matches = [
                row
                for row in self.rows
                if all(row.get(column) == value for column, value in self.filters)
            ]
            for row in matches:
                row.update(self.payload)
            return FakeResponse(matches)
        if self.operation == "delete":
            matches = [
                row
                for row in self.rows
                if all(row.get(column) == value for column, value in self.filters)
            ]
            self.rows[:] = [row for row in self.rows if row not in matches]
            return FakeResponse(matches)
        matches = [
            row
            for row in self.rows
            if all(row.get(column) == value for column, value in self.filters)
        ]
        return FakeResponse(matches)


class FakeSupabase:
    rpc = fake_rpc

    def __init__(self, fighters, tables=None):
        self.rows = {
            "fighters": list(fighters),
            "external_ids": [],
            "fights": [],
            "fight_research": [],
            "odds": [],
            "bet_legs": [],
        }
        self.rows.update(tables or {})

    def table(self, name):
        return FakeQuery(name, self.rows[name])


class UfcImporterRoutingTests(unittest.TestCase):
    def test_attach_mapping_updates_existing_internal_source_mapping(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer.source_id = 7
        importer.supabase = FakeSupabase([])
        importer.supabase.rows["external_ids"].append({
            "external_id_map_id": 64,
            "entity_type": "fight",
            "internal_id": 64,
            "source_id": 7,
            "external_id": "old-espn-fight-id",
        })

        importer._attach_mapping("fight", 64, "new-espn-fight-id")

        self.assertEqual(len(importer.supabase.rows["external_ids"]), 1)
        self.assertEqual(
            importer.supabase.rows["external_ids"][0]["external_id"],
            "new-espn-fight-id",
        )

    def test_placeholder_fight_is_skipped_before_database_matching(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        result = importer.import_fight(
            event_id=99,
            fight={
                "id": "placeholder-fight",
                "competitors": [
                    {
                        "order": 1,
                        "id": "tba-a",
                        "athlete": {
                            "id": "tba-a",
                            "displayName": "Opponent TBA",
                        },
                    },
                    {
                        "order": 2,
                        "id": "tba-b",
                        "athlete": {
                            "id": "tba-b",
                            "displayName": "TBA",
                        },
                    },
                ],
            },
            fight_order=1,
        )
        self.assertEqual(result["status"], "skipped_placeholder")

    def test_safe_first_name_variants_reuse_seeded_dwcs_fighters(self) -> None:
        self.assertEqual(
            fighter_name_key("Joe Kropschot"),
            fighter_name_key("Joseph Kropschot"),
        )
        self.assertEqual(
            fighter_name_key("Tom Pagliarulo"),
            fighter_name_key("Thomas Pagliarulo"),
        )

    def test_routes_ufc_and_dwcs_to_separate_promotions(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer.promotion_id = 1
        importer.dwcs_promotion_id = 2

        self.assertEqual(
            importer._promotion_id_for_event(
                {"id": "1", "name": "UFC 330"}
            ),
            1,
        )
        self.assertEqual(
            importer._promotion_id_for_event(
                {
                    "id": "2",
                    "name": (
                        "Dana White's Contender Series: "
                        "Season 10, Week 1"
                    ),
                }
            ),
            2,
        )

    def test_duplicate_local_names_are_not_guessed(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer._fighter_rows = lambda: [
            {"fighter_id": 10, "full_name": "Gianni Vazquez"},
            {"fighter_id": 22, "full_name": "Gianni Vazquez"},
        ]

        self.assertIsNone(
            importer._find_fighter_by_name("Gianni Vazquez")
        )

    def test_duplicate_name_creates_stable_provider_owned_identity(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer.source_id = 8
        importer.supabase = FakeSupabase([
            {"fighter_id": 10, "full_name": "Gianni Vazquez"},
            {"fighter_id": 22, "full_name": "Gianni Vazquez"},
        ])

        fighter_id = importer.get_or_create_fighter({
            "external_id": "espn-athlete-919",
            "external_url": "https://example.test/athlete/919",
            "name": "Gianni Vazquez",
        })

        self.assertEqual(fighter_id, 23)
        self.assertEqual(
            importer.supabase.rows["external_ids"][0]["internal_id"],
            23,
        )
        self.assertEqual(
            importer.supabase.rows["external_ids"][0]["external_id"],
            "espn-athlete-919",
        )

    def test_existing_mapping_refreshes_current_profile(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer.source_id = 7
        importer.supabase = FakeSupabase([
            {"fighter_id": 10, "full_name": "Mapped Fighter"},
        ])
        importer.supabase.rows["external_ids"].append({
            "entity_type": "fighter",
            "source_id": 7,
            "external_id": "espn-10",
            "internal_id": 10,
        })

        fighter_id = importer.get_or_create_fighter({
            "external_id": "espn-10",
            "name": "Mapped Fighter",
            "profile": {
                "record_summary": "9-1-0",
                "age_snapshot": 27,
                "height_inches": 72,
            },
        })

        self.assertEqual(fighter_id, 10)
        row = importer.supabase.rows["fighters"][0]
        self.assertEqual(row["record_summary"], "9-1-0")
        self.assertEqual(row["age_snapshot"], 27)
        self.assertEqual(row["height_inches"], 72)

    def test_duplicate_matchup_reuses_row_with_saved_user_data(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer.supabase = FakeSupabase([], tables={
            "fights": [
                {
                    "fight_id": 10,
                    "event_id": 5,
                    "fighter_a_id": 1,
                    "fighter_b_id": 2,
                    "fight_status": "scheduled",
                    "fighter_a": {"full_name": "José Silva"},
                    "fighter_b": {"full_name": "John Smith"},
                },
                {
                    "fight_id": 91,
                    "event_id": 5,
                    "fighter_a_id": 77,
                    "fighter_b_id": 88,
                    "fight_status": "scheduled",
                    "fighter_a": {"full_name": "JohnSmith"},
                    "fighter_b": {"full_name": "Jose Silva"},
                },
            ],
            "fight_research": [{
                "research_id": "saved-research",
                "fight_id": 91,
                "bet_side": "fighter_a",
                "user_lean": "fighter_a",
                "confidence": 4,
                "assistant_pick": "fighter_a",
                "assistant_matchup_analysis": "Saved analysis",
            }],
        })

        fight_id = importer._find_existing_fight(
            5,
            1001,
            1002,
            "Jose Silva",
            "John Smith",
        )

        self.assertEqual(fight_id, 91)

    def test_duplicate_matchup_uses_original_row_as_stable_tie_breaker(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer.supabase = FakeSupabase([], tables={
            "fights": [
                {
                    "fight_id": 91,
                    "event_id": 5,
                    "fighter_a_id": 77,
                    "fighter_b_id": 88,
                    "fight_status": "scheduled",
                    "fighter_a": {"full_name": "John Smith"},
                    "fighter_b": {"full_name": "Jose Silva"},
                },
                {
                    "fight_id": 10,
                    "event_id": 5,
                    "fighter_a_id": 1,
                    "fighter_b_id": 2,
                    "fight_status": "scheduled",
                    "fighter_a": {"full_name": "José Silva"},
                    "fighter_b": {"full_name": "John Smith"},
                },
            ],
        })

        fight_id = importer._find_existing_fight(
            5,
            1001,
            1002,
            "Jose Silva",
            "John Smith",
        )

        self.assertEqual(fight_id, 10)

    def test_import_refuses_to_move_a_provider_mapping_between_historical_rows(self) -> None:
        importer = UfcImporter.__new__(UfcImporter)
        importer.source_id = 7
        importer.promotion_label = "UFC"
        importer.supabase = FakeSupabase([], tables={
            "fights": [
                {
                    "fight_id": 10,
                    "event_id": 5,
                    "fighter_a_id": 1,
                    "fighter_b_id": 2,
                    "fight_status": "scheduled",
                    "fighter_a": {"full_name": "Jose Silva"},
                    "fighter_b": {"full_name": "John Smith"},
                },
                {
                    "fight_id": 91,
                    "event_id": 5,
                    "fighter_a_id": 77,
                    "fighter_b_id": 88,
                    "fight_status": "scheduled",
                    "fighter_a": {"full_name": "JohnSmith"},
                    "fighter_b": {"full_name": "José Silva"},
                },
            ],
            "external_ids": [{
                "external_id_map_id": 4,
                "entity_type": "fight",
                "internal_id": 91,
                "source_id": 7,
                "external_id": "provider-current-id",
            }],
            "fight_research": [{
                "research_id": "saved-research",
                "fight_id": 10,
                "bet_side": "fighter_a",
                "user_lean": "fighter_a",
                "confidence": 4,
                "assistant_pick": "fighter_a",
                "assistant_matchup_analysis": "Saved analysis",
            }],
        })
        importer.get_or_create_fighter = lambda fighter: (
            1 if fighter["name"] == "Jose Silva" else 2
        )
        importer._weight_class_id = lambda _name: None

        before=deepcopy(importer.supabase.rows)
        with self.assertRaisesRegex(RuntimeError,"mapped identity"):
            importer.import_fight(
                event_id=5,
                fight={
                    "id": "provider-current-id",
                    "matchNumber": 3,
                    "competitors": [
                        {
                            "order": 1,
                            "athlete": {
                                "id": "athlete-a",
                                "displayName": "Jose Silva",
                            },
                        },
                        {
                            "order": 2,
                            "athlete": {
                                "id": "athlete-b",
                                "displayName": "John Smith",
                            },
                        },
                    ],
                },
                fight_order=3,
            )
        self.assertEqual(importer.supabase.rows,before)


if __name__ == "__main__":
    unittest.main()
