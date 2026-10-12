from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path


PROVIDER_ROOT = Path(__file__).resolve().parent


class ImportCurrentOddsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(PROVIDER_ROOT))

        fake_client = types.ModuleType("client")
        fake_client.get_current_mma_moneylines = lambda: ([], {})
        sys.modules["client"] = fake_client

        fake_matcher = types.ModuleType("fight_matcher")
        fake_matcher.load_database_fights = lambda: []
        fake_matcher.match_api_fight = lambda *_args: {}
        sys.modules["fight_matcher"] = fake_matcher

        fake_importer = types.ModuleType("import_one_matchup")
        fake_importer.create_external_mapping = lambda *_args: None
        fake_importer.get_existing_external_mapping = lambda *_args: None
        fake_importer.get_odds_source_id = lambda: 1
        fake_importer.import_moneylines = lambda *_args: {}
        sys.modules["import_one_matchup"] = fake_importer

        cls.module = importlib.import_module("import_current_odds")

    @classmethod
    def tearDownClass(cls) -> None:
        sys.path.remove(str(PROVIDER_ROOT))
        for name in (
            "import_current_odds",
            "client",
            "fight_matcher",
            "import_one_matchup",
        ):
            sys.modules.pop(name, None)

    def test_finds_an_existing_external_mapping_target(self) -> None:
        fight = {"fight_id": 42}

        resolved = self.module.find_database_fight(
            [fight],
            42,
        )

        self.assertIs(resolved, fight)

    def test_returns_none_for_mapping_to_deleted_fight(self) -> None:
        resolved = self.module.find_database_fight(
            [{"fight_id": 41}],
            42,
        )

        self.assertIsNone(resolved)

    def test_configures_console_for_unicode_fighter_names(self) -> None:
        class FakeStream:
            def __init__(self) -> None:
                self.options = None

            def reconfigure(self, **options) -> None:
                self.options = options

        stdout = FakeStream()
        stderr = FakeStream()
        original_stdout = self.module.sys.stdout
        original_stderr = self.module.sys.stderr
        try:
            self.module.sys.stdout = stdout
            self.module.sys.stderr = stderr
            self.module.configure_utf8_console()
        finally:
            self.module.sys.stdout = original_stdout
            self.module.sys.stderr = original_stderr

        self.assertEqual(
            stdout.options,
            {"encoding": "utf-8", "errors": "backslashreplace"},
        )
        self.assertEqual(stderr.options, stdout.options)


if __name__ == "__main__":
    unittest.main()
