import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.apply_patch_bundle import install_patch, replace_bytes, restore_patch


def checksum(data):
    return hashlib.sha256(data).hexdigest()


class PatchBundleTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="mma-patch-test-")
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.dashboard = self.root / "MMA-Dashboard"
        (self.dashboard / "api/sync").mkdir(parents=True)
        (self.dashboard / "src").mkdir()
        (self.dashboard / "package.json").write_text('{"version":"12.1.0"}')
        (self.dashboard / "api/sync/weekly_sync.py").write_bytes(b"original\n")
        (self.dashboard / ".env").write_bytes(b"local-settings\n")
        self.bundle = self.root / "bundle"
        self.payload = self.bundle / "payload"
        self.payload.mkdir(parents=True)
        self.items = {}
        self.file("api/sync/weekly_sync.py", b"patched\n", [checksum(b"original\n")])
        self.file("api/providers/pfl_official/new.py", b"new-file\n", [None])

    def file(self, name, data, allowed):
        target = self.payload / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        self.items[name] = {"sha256": checksum(data), "allowed_before": allowed}
        self.manifest()

    def manifest(self):
        (self.bundle / "PATCH-MANIFEST.json").write_text(json.dumps({"patch": "test", "files": self.items}))

    def test_install_backs_up_originals_and_does_not_change_settings(self):
        backup = install_patch(self.bundle, self.dashboard)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_bytes(), b"patched\n")
        self.assertEqual((backup / "files/api/sync/weekly_sync.py").read_bytes(), b"original\n")
        self.assertEqual((self.dashboard / ".env").read_bytes(), b"local-settings\n")
        self.assertTrue((backup / "RESTORE-PATCH.bat").is_file())

    def test_repeated_install_does_not_make_another_backup(self):
        backup = install_patch(self.bundle, self.dashboard)
        self.assertIsNone(install_patch(self.bundle, self.dashboard))
        self.assertEqual(list(backup.parent.iterdir()), [backup])

    def test_recovery_restores_originals_and_removes_files_added_by_the_patch(self):
        backup = install_patch(self.bundle, self.dashboard)
        restore_patch(backup)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_bytes(), b"original\n")
        self.assertFalse((self.dashboard / "api/providers/pfl_official/new.py").exists())
        self.assertEqual((self.dashboard / ".env").read_bytes(), b"local-settings\n")
        restore_patch(backup)  # Recovery is repeatable.

    def test_checksum_failure_stops_before_any_source_file_is_changed(self):
        (self.payload / "api/providers/pfl_official/new.py").write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "could not be verified"):
            install_patch(self.bundle, self.dashboard)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_bytes(), b"original\n")
        self.assertFalse((self.root / "MMA-patch-backups").exists())

    def test_locally_edited_source_is_preserved(self):
        (self.dashboard / "api/sync/weekly_sync.py").write_bytes(b"user-edit\n")
        with self.assertRaisesRegex(ValueError, "differs from"):
            install_patch(self.bundle, self.dashboard)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_bytes(), b"user-edit\n")

    def test_write_failure_restores_only_the_files_already_written(self):
        calls = []
        def write(target, data):
            calls.append(target)
            if len(calls) == 2:
                raise OSError("Simulated write failure")
            replace_bytes(target, data)
        with patch("scripts.apply_patch_bundle.replace_bytes", side_effect=write):
            with self.assertRaises(OSError):
                install_patch(self.bundle, self.dashboard)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_bytes(), b"original\n")
        self.assertFalse((self.dashboard / "api/providers/pfl_official/new.py").exists())

    def test_recovery_preserves_edits_made_after_installation(self):
        backup = install_patch(self.bundle, self.dashboard)
        (self.dashboard / "api/sync/weekly_sync.py").write_bytes(b"later-user-edit\n")
        with self.assertRaisesRegex(ValueError, "changed after"):
            restore_patch(backup)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_bytes(), b"later-user-edit\n")
        self.assertTrue((self.dashboard / "api/providers/pfl_official/new.py").exists())

    def test_settings_files_and_traversal_are_rejected(self):
        for name in ("api/.env", "../outside.py"):
            self.items[name] = {"sha256": "unknown", "allowed_before": [None]}
            self.manifest()
            with self.assertRaisesRegex(ValueError, "unsupported file path"):
                install_patch(self.bundle, self.dashboard)
            self.items.pop(name)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_bytes(), b"original\n")


if __name__ == "__main__":
    unittest.main()
