import json
from pathlib import Path
import re
import unittest
from scripts.build_upgrade import build_upgrade

ROOT = Path(__file__).resolve().parents[2]


class ReleaseContractTests(unittest.TestCase):
    def test_distributed_locks_match_the_tested_runtime(self):
        lock = (ROOT / "requirements.lock").read_bytes()
        self.assertEqual((ROOT / "api" / "requirements.txt").read_bytes(), lock)
        self.assertEqual(
            (ROOT / "discord-companion" / "requirements.txt").read_bytes(), lock
        )

    def test_dashboard_and_discord_require_the_same_provider_contract(self):
        manifest = json.loads(
            (ROOT / "api" / "providers" / "manifest.json").read_text()
        )
        expected = re.search(
            r'EXPECTED_PROVIDER_CORE_VERSION = "([^"]+)"',
            (ROOT / "discord-companion" / "provider_runtime.py").read_text(),
        )[1]
        self.assertEqual(manifest["provider_core_version"], expected)

    def test_combined_upgrade_matches_the_reviewed_migrations(self):
        self.assertEqual(
            (ROOT / "supabase" / "upgrade-personal-12.1.0.sql").read_text(),
            build_upgrade(),
        )
