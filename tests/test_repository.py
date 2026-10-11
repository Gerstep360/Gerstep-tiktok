"""Real Git updates in disposable repositories, never the developer checkout."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.repository import refresh


class UI:
    def say(self, *args): pass
    @contextmanager
    def step(self, *args): yield


class Runner:
    def run(self, args, **kwargs):
        return subprocess.run(args, capture_output=True, timeout=kwargs.get('timeout', 10), check=True).returncode
    def capture(self, args):
        return subprocess.check_output(args, text=True, timeout=10)


@unittest.skipUnless(shutil.which('git'), 'Git required for standalone update tests')
class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='gerstep-git-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.remote, self.seed, self.clone = [self.root / name for name in ('origin.git', 'seed', 'checkout')]
        self.runner = Runner()
        self.runner.run(['git', 'init', '--bare', '--initial-branch=main', str(self.remote)])
        self.runner.run(['git', 'init', '--initial-branch=main', str(self.seed)])
        for key, value in (('user.name', 'Gerstep Test'), ('user.email', 'test@example.test'),
                           ('commit.gpgsign', 'false'), ('core.hooksPath', str(self.root / 'no-hooks'))):
            self.git(self.seed, 'config', key, value)
        (self.seed / 'backend').mkdir()
        (self.seed / 'frontend').mkdir()
        (self.seed / 'backend/server.py').write_text('old version')
        (self.seed / 'frontend/package.json').write_text('{}')
        self.git(self.seed, 'add', '.')
        self.git(self.seed, 'commit', '-m', 'Initial test version')
        self.git(self.seed, 'remote', 'add', 'origin', str(self.remote))
        self.git(self.seed, 'push', 'origin', 'main')
        self.runner.run(['git', 'clone', str(self.remote), str(self.clone)])

    def git(self, repo, *args):
        self.runner.run(['git', '-C', str(repo), *args])

    def test_fetch_then_hard_reset_updates_code_and_keeps_untracked_secrets(self):
        (self.seed / 'backend/server.py').write_text('new version')
        self.git(self.seed, 'commit', '-am', 'New test version')
        self.git(self.seed, 'push', 'origin', 'main')
        (self.clone / 'backend/server.py').write_text('local edit to overwrite')
        (self.clone / '.env').write_text('private fixture')
        (self.clone / 'data').mkdir()
        (self.clone / 'data/database').write_text('keep fixture data')
        # Runtime app is independent of the source checkout.
        app = self.root / 'runtime'
        app.mkdir()
        (app / 'database').write_text('live data')
        self.assertEqual(refresh(self.clone, app, {}, UI(), self.runner), self.clone)
        self.assertEqual((self.clone / 'backend/server.py').read_text(), 'new version')
        self.assertEqual((self.clone / '.env').read_text(), 'private fixture')
        self.assertEqual((self.clone / 'data/database').read_text(), 'keep fixture data')
        self.assertEqual((app / 'database').read_text(), 'live data')

    def test_installed_menu_uses_saved_source_checkout(self):
        app = self.root / 'runtime'
        app.mkdir()
        self.assertEqual(refresh(app, app, {'GERSTEP_SOURCE_REPO': str(self.clone)}, UI(), self.runner), self.clone)

    def test_fetch_failure_never_resets_local_code(self):
        original_run = self.runner.run
        def fail_fetch(args, **kwargs):
            if 'fetch' in args: raise RuntimeError('offline fixture')
            return original_run(args, **kwargs)
        (self.clone / 'backend/server.py').write_text('local edit')
        with patch.object(self.runner, 'run', fail_fetch), self.assertRaisesRegex(RuntimeError, 'offline fixture'):
            refresh(self.clone, self.root / 'runtime', {}, UI(), self.runner)
        self.assertEqual((self.clone / 'backend/server.py').read_text(), 'local edit')

    def test_refuses_parent_repository_and_runtime_directory(self):
        with self.assertRaisesRegex(RuntimeError, 'fuera de'):
            refresh(self.clone, self.clone, {}, UI(), self.runner)
        with patch.object(self.runner, 'capture', return_value=str(self.root)), self.assertRaisesRegex(RuntimeError, 'no coincide'):
            refresh(self.clone, self.root / 'runtime', {}, UI(), self.runner)

    def test_install_without_checkout_does_not_touch_a_parent_repository(self):
        app = self.root / 'runtime'
        with patch.object(self.runner, 'run', side_effect=AssertionError('Git must not run')):
            self.assertIsNone(refresh(app, app, {}, UI(), self.runner))
