from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.apply_patch_bundle import replace_bytes, restore_patch
from scripts.apply_personal_update import default_companion, install_pair


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PairedUpdateTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix='mma-paired-update-')
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.bundle = self.root / 'bundle'
        self.dashboard, self.companion = self.root / 'dashboard', self.root / 'bot'
        (self.dashboard / 'api/sync').mkdir(parents=True)
        (self.dashboard / 'src').mkdir()
        (self.dashboard / 'package.json').write_text('{"version":"12.1.0"}')
        (self.dashboard / 'api/sync/weekly_sync.py').write_bytes(b'original-dashboard\n')
        self.companion.mkdir()
        for name in ('sync_discord.py', 'run_bot.py', 'provider_runtime.py'):
            (self.companion / name).write_bytes(b'original-bot\n')
        self.files = {'dashboard': ('api/sync/weekly_sync.py', b'original-dashboard\n', b'new-dashboard\n'),
                      'companion': ('sync_discord.py', b'original-bot\n', b'new-bot\n')}
        for component, (name, before, after) in self.files.items():
            bundle = self.bundle / component
            source = bundle / 'payload' / name
            source.parent.mkdir(parents=True)
            source.write_bytes(after)
            (bundle / 'PATCH-MANIFEST.json').write_text(json.dumps({'component': component,
                'patch': 'data-disputes', 'files': {name: {'sha256': digest(after),
                                                        'allowed_before': [digest(before)]}}}))
        for root in (self.dashboard, self.companion):
            (root / '.env').write_bytes(b'LOCAL_SETTINGS_KEEP=1\n')
        (self.companion / 'sync-state.json').write_bytes(b'{"saved-posts":"keep"}')

    def originals(self):
        for component, root in (('dashboard', self.dashboard), ('companion', self.companion)):
            name, before, _ = self.files[component]
            self.assertEqual((root / name).read_bytes(), before)

    def test_both_components_install_and_restore_without_changing_settings_or_state(self):
        backups = install_pair(self.bundle, self.dashboard, self.companion)
        self.assertEqual(len(backups), 2)
        self.assertEqual((self.dashboard / '.env').read_bytes(), b'LOCAL_SETTINGS_KEEP=1\n')
        self.assertEqual((self.companion / '.env').read_bytes(), b'LOCAL_SETTINGS_KEEP=1\n')
        self.assertEqual((self.companion / 'sync-state.json').read_bytes(), b'{"saved-posts":"keep"}')
        self.assertEqual(install_pair(self.bundle, self.dashboard, self.companion), [])
        for backup in reversed(backups):
            restore_patch(backup)
        self.originals()

    def test_incompatible_bot_is_detected_before_dashboard_changes(self):
        (self.companion / 'sync_discord.py').write_bytes(b'local-bot-edit\n')
        with self.assertRaisesRegex(ValueError, 'differs from'):
            install_pair(self.bundle, self.dashboard, self.companion)
        self.assertEqual((self.dashboard / 'api/sync/weekly_sync.py').read_bytes(), b'original-dashboard\n')
        self.assertFalse((self.root / 'MMA-patch-backups').exists())

    def test_a_bot_copy_failure_restores_the_dashboard_to_its_original_version(self):
        def replace(target, data):
            if target == self.companion / 'sync_discord.py' and data == b'new-bot\n':
                raise OSError('Simulated bot copy failure')
            replace_bytes(target, data)
        with patch('scripts.apply_patch_bundle.replace_bytes', side_effect=replace):
            with self.assertRaisesRegex(OSError, 'bot copy failure'):
                install_pair(self.bundle, self.dashboard, self.companion)
        self.originals()

    def test_the_known_working_bot_folder_can_be_found_under_the_older_name(self):
        desktop = self.root / 'Desktop'
        bot = desktop / 'MMA Tracker/discord/MMA-Discord-Starter-v1/MMA-Discord-Starter'
        bot.mkdir(parents=True)
        for name in ('sync_discord.py', 'run_bot.py', '.env'):
            (bot / name).write_bytes(b'present\n')
        self.assertEqual(default_companion(self.dashboard, [desktop]), bot.resolve())


if __name__ == '__main__':
    unittest.main()
