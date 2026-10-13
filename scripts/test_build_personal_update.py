from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts.build_personal_update import build_update
from scripts.apply_personal_update import install_pair


class GitUpdateTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.git("init", "-q")
        for name, text in {".gitignore": ".env\nsync-state.json\n",
                           "package.json": '{"version":"12.1.0"}',
                           "api/sync/weekly_sync.py": "before\n", "src/App.jsx": "before UI\n",
                           "discord-companion/sync_discord.py": "before bot\n",
                           "discord-companion/run_bot.py": "runner\n",
                           "discord-companion/provider_runtime.py": "provider\n"}.items():
            target = self.source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.commit()
        self.base = self.git("rev-parse", "HEAD").decode().strip()
        self.dashboard = self.root / "dashboard"
        self.bot = self.root / "bot"
        shutil.copytree(self.source, self.dashboard, ignore=shutil.ignore_patterns(".git"))
        shutil.copytree(self.source / "discord-companion", self.bot)
        for target in (self.dashboard, self.bot):
            (target / ".env").write_text("private settings\n")
        (self.bot / "sync-state.json").write_text('{"events":{"622":{"channel_id":"existing"}}}')
        (self.source / "api/sync/weekly_sync.py").write_text("after\n")
        (self.source / "src/App.jsx").write_text("after UI\n")
        (self.source / "discord-companion/sync_discord.py").write_text("after bot\n")
        self.commit()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.source), *args], check=True,
                              capture_output=True).stdout

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "Fixture")

    def test_git_update_preserves_both_installations_settings_and_state_and_is_repeatable(self):
        (self.source / ".env").write_text("never package this\n")
        bundle = build_update(self.source, self.base, self.root / "update")
        self.assertEqual(list(bundle.rglob(".env")), [])
        backups = install_pair(bundle, self.dashboard, self.bot)
        self.assertEqual(len(backups), 2)
        self.assertEqual((self.dashboard / "src/App.jsx").read_text(), "after UI\n")
        self.assertEqual((self.bot / "sync_discord.py").read_text(), "after bot\n")
        self.assertEqual((self.bot / ".env").read_text(), "private settings\n")
        self.assertIn("existing", (self.bot / "sync-state.json").read_text())
        self.assertEqual(install_pair(bundle, self.dashboard, self.bot), [])

    def test_dirty_source_or_locally_edited_bot_stops_before_touching_either_installation(self):
        (self.source / "src/App.jsx").write_text("local change\n")
        with self.assertRaisesRegex(ValueError, "local edits"):
            build_update(self.source, self.base, self.root / "dirty-update")
        self.git("restore", "src/App.jsx")
        bundle = build_update(self.source, self.base, self.root / "update")
        (self.bot / "sync_discord.py").write_text("local bot change\n")
        with self.assertRaisesRegex(ValueError, "differs from"):
            install_pair(bundle, self.dashboard, self.bot)
        self.assertEqual((self.dashboard / "api/sync/weekly_sync.py").read_text(), "before\n")
        self.assertEqual((self.bot / "sync_discord.py").read_text(), "local bot change\n")

    def test_removed_files_require_review_instead_of_silently_incomplete_updates(self):
        (self.source / "src/App.jsx").unlink()
        self.commit()
        with self.assertRaisesRegex(ValueError, "removed or renamed"):
            build_update(self.source, self.base, self.root / "update")
