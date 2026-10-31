"""Program-managed settings; isolated LOCALAPPDATA, never production materials."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import cli_settings as settings
import eyepqc


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'user'))
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def call(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = eyepqc.main(list(args))
        return code, output.getvalue(), errors.getvalue()

    def test_no_json_uses_built_in_defaults_without_creating_settings(self):
        with patch.object(settings, 'read_json', side_effect=AssertionError('no JSON expected')):
            code, output, _ = self.call('config', 'show')
        shown = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(shown['source'], 'built-in-defaults')
        self.assertEqual(shown['config']['tunnel']['host'], '203.0.113.10')
        self.assertIsNone(shown['config']['serial_port'])
        self.assertFalse(settings.settings_path().exists())

    def test_set_changes_only_requested_key_and_toggle_retains_paths(self):
        before = settings.effective()
        self.assertEqual(self.call('config', 'set', 'serial_port', 'COM7')[0], 0)
        after = settings.effective()
        self.assertEqual(after, dict(before, serial_port='COM7'))
        self.assertEqual(self.call('config', 'set', 'tunnel.enabled', 'false')[0], 0)
        saved_tunnel = settings.effective()['tunnel']
        self.assertFalse(saved_tunnel['enabled'])
        self.assertEqual(saved_tunnel['identity_file'], before['tunnel']['identity_file'])
        self.assertEqual(self.call('config', 'set', 'tunnel.enabled', 'true')[0], 0)
        self.assertEqual(settings.effective()['tunnel'], before['tunnel'])
        self.assertEqual(self.call('config', 'set', 'serial_port', 'auto')[0], 0)
        self.assertIsNone(settings.effective()['serial_port'])
        self.assertEqual(json.loads(self.call('config', 'show')[1])['source'], 'user-settings')

    def test_relative_set_path_uses_callers_cwd_without_requiring_file(self):
        self.assertEqual(self.call('config', 'set', 'accounts_file', 'does-not-exist/accounts.json')[0], 0)
        self.assertEqual(settings.effective()['accounts_file'], str((Path.cwd() / 'does-not-exist/accounts.json').resolve()))

    def legacy(self):
        config = settings.defaults()
        del config['tunnel']['enabled']
        config['accounts_file'] = 'relative/accounts.json'
        return config

    def test_import_relative_paths_and_disabled_tunnel_preserve_existing_details(self):
        path = self.root / 'legacy.json'
        record = self.legacy()
        path.write_text(json.dumps(record))
        self.assertEqual(self.call('config', 'import', str(path))[0], 0)
        self.assertEqual(settings.effective()['accounts_file'], str(self.root / 'relative/accounts.json'))
        tunnel = settings.effective()['tunnel']
        record['tunnel'] = None
        path.write_text(json.dumps(record))
        self.assertEqual(self.call('config', 'import', str(path))[0], 0)
        self.assertEqual(settings.effective()['tunnel'], dict(tunnel, enabled=False))

    def test_invalid_keys_types_hosts_ports_and_paths_do_not_write(self):
        settings.set_value('serial_port', 'COM7')
        original = settings.settings_path().read_bytes()
        for key, value in (('tunnel.enabled', 'yes'), ('tunnel.ssh_port', 'true'),
                           ('tunnel.ssh_port', '65536'), ('tunnel.host', 'user@host'),
                           ('tunnel.host', '999.1.1.1'), ('tls_key', '//remote/key'),
                           ('tunnel.identity_file', '$HOME/key'), ('serial_port', 'COM\n7')):
            with self.subTest(key=key):
                self.assertEqual(self.call('config', 'set', key, value)[0], 1)
                self.assertEqual(settings.settings_path().read_bytes(), original)
        with self.assertRaises(ValueError):
            settings.set_value('password', 'not-allowed')

    def test_corrupt_existing_settings_block_show_set_import_and_preserve_bytes(self):
        path = settings.settings_path()
        path.parent.mkdir(parents=True)
        imported = self.root / 'valid.json'
        imported.write_text(json.dumps(self.legacy()))
        for data in (b'{"version":1,"version":1}', b' ' * 16385,
                     json.dumps(settings.defaults() | {'password': 'secret-never-print'}).encode(), b'{broken'):
            path.write_bytes(data)
            for args in (('show',), ('set', 'serial_port', 'COM7'), ('import', str(imported))):
                code, out, err = self.call('config', *args)
                self.assertEqual(code, 1)
                self.assertNotIn('secret-never-print', out + err)
                self.assertEqual(path.read_bytes(), data)

    def test_atomic_replace_failure_keeps_old_settings_and_cleans_temporary_file(self):
        settings.set_value('serial_port', 'COM7')
        original = settings.settings_path().read_bytes()
        with patch.object(settings.os, 'replace', side_effect=PermissionError('fixture')):
            self.assertEqual(self.call('config', 'set', 'serial_port', 'COM8')[0], 1)
        self.assertEqual(settings.settings_path().read_bytes(), original)
        self.assertEqual(list(settings.settings_path().parent.glob('.settings-*.tmp')), [])

    def test_config_commands_open_no_materials_or_services(self):
        with patch.object(eyepqc, 'check_materials', side_effect=AssertionError('private read')), patch.object(
                eyepqc.cloud_tunnel, 'command', side_effect=AssertionError('SSH')), patch.object(
                eyepqc, 'run_services', side_effect=AssertionError('network')):
            self.assertEqual(self.call('config', 'show')[0], 0)
            self.assertEqual(self.call('config', 'set', 'tls_key', 'missing-file.pem')[0], 0)

    def test_localappdata_rejects_relative_unc_or_missing(self):
        for value in ('', 'relative', '//remote/user', '\\\\remote\\user'):
            with self.subTest(value=value), patch.dict(os.environ, LOCALAPPDATA=value):
                self.assertEqual(self.call('config', 'show')[0], 1)

    def test_unrelated_commands_and_explicit_legacy_config_ignore_broken_settings(self):
        record = self.legacy()
        record['tunnel'] = None
        with patch.dict(os.environ, LOCALAPPDATA='invalid-relative'):
            self.assertEqual(self.call()[0], 0)
            with patch.object(eyepqc, 'status'):
                self.assertEqual(self.call('status')[0], 0)
            with patch.object(eyepqc.getpass, 'getpass', return_value='fixture'), patch.object(eyepqc.accounts, 'create_account'):
                self.assertEqual(self.call('account', '--file', str(self.root / 'new'), '--username', 'fixture')[0], 0)
            path = self.root / 'legacy.json'
            path.write_text(json.dumps(record))
            with patch.object(Path, 'is_file', return_value=True), patch.object(Path, 'stat') as stat:
                stat.return_value.st_size = 1
                args, ssh = eyepqc.load_config(path)
            self.assertIsNone(ssh)


class FrozenConfigurationTests(unittest.TestCase):
    def test_new_exe_manages_isolated_user_settings_without_adjacent_json(self):
        directory = Path(__file__).resolve().parents[2] / 'build/pc_cli/dist'
        version = eyepqc.VERSION
        exe = directory / ('eyepqc-' + version + '.exe')
        if not exe.exists():
            self.skipTest('build the current PC version first')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = dict(os.environ, LOCALAPPDATA=str(root / 'user'))

            def run(*args):
                return subprocess.run([str(exe), *args], capture_output=True, text=True, env=env, timeout=30, cwd=root)

            result = run('config', 'show')
            self.assertEqual(result.returncode, 0, result.stderr)
            shown = json.loads(result.stdout)
            self.assertEqual(shown['source'], 'built-in-defaults')
            self.assertIsNone(shown['config']['serial_port'])
            self.assertEqual(run('config', 'set', 'tunnel.enabled', 'false').returncode, 0)
            self.assertEqual(run('config', 'set', 'serial_port', 'COM99').returncode, 0)
            self.assertEqual(run('config', 'set', 'tls_key', 'missing.pem').returncode, 0)
            legacy = copy.deepcopy(shown['config'])
            del legacy['tunnel']['enabled']
            legacy['tunnel'] = None
            legacy['accounts_file'] = 'relative/accounts.json'
            path = root / 'old.json'
            path.write_text(json.dumps(legacy))
            self.assertEqual(run('config', 'import', str(path)).returncode, 0)
            after = json.loads(run('config', 'show').stdout)
            self.assertEqual(after['config']['accounts_file'], str(root / 'relative/accounts.json'))
            self.assertFalse(after['config']['tunnel']['enabled'])
            self.assertEqual(run('check').returncode, 1)  # Missing fixture materials, never USB/network.
            managed = Path(after['settings_file'])
            managed.write_text('{broken')
            self.assertEqual(run('config', 'set', 'serial_port', 'COM7').returncode, 1)
            self.assertEqual(managed.read_text(), '{broken')
            self.assertEqual(run('--help').returncode, 0)
            self.assertIn(version, run('--version').stdout)
