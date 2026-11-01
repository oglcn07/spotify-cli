"""Offline checks for portable installs, OAuth isolation and launcher quoting."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import install
import watch_config


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / 'config'
        for name, value in [('CONFIG_DIR', self.config), ('CLIENT_CONFIG', self.config / 'oauth.json'),
                            ('LEGACY_CLIENT', self.root / '.spotify-client-id'), ('LEGACY_CACHE', self.root / '.token-cache')]:
            mocked = patch.object(watch_config, name, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('SPOTIFY_CLIENT_ID', None)

    def test_configure_roundtrip_and_private_token_permissions(self):
        selected = 'a' * 32
        watch_config.save_client_id(selected)
        self.assertEqual(watch_config.client_id(), selected)
        path = watch_config.token_cache_path(selected)
        cache = watch_config.PrivateTokenCache(cache_path=str(path))
        cache.save_token_to_cache({'access_token': 'fake-test-token'})
        self.assertEqual(cache.get_cached_token()['access_token'], 'fake-test-token')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(watch_config.CLIENT_CONFIG.stat().st_mode & 0o777, 0o600)

    def test_legacy_cache_is_only_reused_for_original_client(self):
        watch_config.LEGACY_CLIENT.write_text('a' * 32)
        watch_config.LEGACY_CACHE.write_text('{}')
        self.assertEqual(watch_config.client_id(), 'a' * 32)
        self.assertEqual(watch_config.token_cache_path('a' * 32), watch_config.LEGACY_CACHE)
        with patch.dict(os.environ, {'SPOTIFY_CLIENT_ID': 'b' * 32}):
            self.assertEqual(watch_config.client_id(), 'b' * 32)
            self.assertNotEqual(watch_config.token_cache_path('b' * 32), watch_config.LEGACY_CACHE)

    def test_missing_client_does_not_use_maintainer_app(self):
        with self.assertRaisesRegex(RuntimeError, 'spotify configure'):
            watch_config.client_id()
        for value in ('secret', 'x' * 32, '', '../' + 'a' * 32):
            with self.assertRaises(ValueError):
                watch_config.save_client_id(value)
        self.assertFalse(watch_config.CLIENT_CONFIG.exists())

    def test_launcher_quotes_checkout_path_and_forwards_arguments(self):
        project = self.root / "repo ' spaces $(touch injection)"
        (project / '.venv/bin').mkdir(parents=True)
        (project / '.venv/bin/python').symlink_to(sys.executable)
        (project / 'spotify.py').write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
        launcher = self.root / 'spotify'
        launcher.write_text(install.launcher_text(project))
        launcher.chmod(0o755)
        arguments = ['play', 'Şarkı adı', '$HOME', '$(touch unsafe)']
        output = subprocess.run([str(launcher), *arguments], text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(output.stdout), arguments)
        self.assertFalse((self.root / 'unsafe').exists())

    def test_installer_preserves_unrelated_launcher_and_existing_service(self):
        home = self.root / 'home'
        project = self.root / 'project'
        (home / '.local/bin').mkdir(parents=True)
        launcher = home / '.local/bin/spotify'
        launcher.write_text('unrelated command')
        with self.assertRaises(RuntimeError):
            install.install(project, home, skip_deps=True, no_service=True)
        self.assertEqual(launcher.read_text(), 'unrelated command')
        (project / '.venv/bin').mkdir(parents=True)
        (project / '.venv/bin/python').touch()
        unit = home / '.config/systemd/user/soloist.service'
        unit.parent.mkdir(parents=True)
        unit.write_text('custom service')
        with patch('install.subprocess.run') as run, patch('builtins.print'):
            install.install(project, home, skip_deps=True, replace_launcher=True)
        self.assertEqual(unit.read_text(), 'custom service')
        self.assertIn(install.MARKER, launcher.read_text())
        run.assert_called_once_with(['systemctl', '--user', 'daemon-reload'], check=True)

    def test_dry_run_does_not_write_files_or_start_processes(self):
        with patch('install.subprocess.run') as run, patch('builtins.print'):
            install.install(self.root / 'missing-project', self.root / 'missing-home', dry_run=True)
        run.assert_not_called()
        self.assertFalse((self.root / 'missing-project').exists())
        self.assertFalse((self.root / 'missing-home').exists())


if __name__ == '__main__':
    unittest.main()
