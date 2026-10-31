"""Fresh local setup never invents identities or permits an incomplete relay."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import cli_settings
import eyepqc
import install_data
from private_acl import private_acl


class InitializeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'user'))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.settings = cli_settings.settings_path()
        self.data = self.settings.parent / 'data'

    def test_new_directories_have_private_acl_and_no_credentials_or_cloud_enabled(self):
        install_data.initialize()
        self.assertEqual(sorted(path.name for path in self.data.iterdir()), ['private', 'public'])
        self.assertEqual(list((self.data / 'private').iterdir()), [])
        self.assertEqual(list((self.data / 'public').iterdir()), [])
        private_acl(self.data / 'private')
        config = cli_settings.effective()
        self.assertFalse(config['tunnel']['enabled'])
        self.assertEqual(config['accounts_file'], str(self.data / 'private/accounts.json'))
        self.assertEqual(config['tls_key'], str(self.data / 'private/server-key.pem'))

    def test_existing_settings_or_partial_data_are_never_replaced(self):
        self.settings.parent.mkdir(parents=True)
        for original in ('{broken', json.dumps(cli_settings.defaults())):
            self.settings.write_text(original)
            with self.assertRaises(FileExistsError):
                install_data.initialize()
            self.assertEqual(self.settings.read_text(), original)
            self.assertFalse(self.data.exists())
        self.settings.unlink()
        self.data.mkdir()
        marker = self.data / 'keep.txt'
        marker.write_text('existing-user-data')
        with self.assertRaises(FileExistsError):
            install_data.initialize()
        self.assertEqual(marker.read_text(), 'existing-user-data')

    def test_acl_failure_rolls_back_only_new_empty_directories(self):
        with patch.object(install_data, 'private_acl', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                install_data.initialize()
        self.assertFalse(self.data.exists())
        self.assertFalse(self.settings.exists())

    def test_settings_commit_failure_leaves_no_materials(self):
        with patch.object(install_data.os, 'fsync', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                install_data.initialize()
        self.assertFalse(self.data.exists())
        self.assertFalse(self.settings.exists())

    def test_concurrent_settings_creation_after_preflight_is_not_overwritten(self):
        original_open = install_data.os.open
        record = json.dumps(cli_settings.defaults()).encode()

        def concurrent_writer(path, flags, *args, **kwargs):
            if Path(path) == self.settings:
                self.settings.write_bytes(record)
            return original_open(path, flags, *args, **kwargs)

        with patch.object(install_data.os, 'open', side_effect=concurrent_writer):
            with self.assertRaises(FileExistsError):
                install_data.initialize()
        self.assertEqual(self.settings.read_bytes(), record)
        self.assertFalse(self.data.exists())

    def test_cli_init_reports_local_incomplete_status_without_details(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(eyepqc.main(['init']), 0)
        self.assertIn('LOCAL_INIT_OK', output.getvalue())
        self.assertIn('runtime_ready=false', output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(eyepqc.main(['init']), 1)

    def test_incomplete_init_cannot_open_usb_or_start_relay(self):
        install_data.initialize()
        with patch.object(eyepqc, 'ensure_port_free'), patch.object(eyepqc, 'run_services') as run, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(eyepqc.main(['run']), 1)
        run.assert_not_called()

    def test_init_then_first_account_add_creates_database_without_default_password(self):
        install_data.initialize()
        password = 'isolated-first-account-fixture'
        with patch.object(eyepqc.getpass, 'getpass', return_value=password), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(eyepqc.main(['account', 'add', '--username', 'first']), 0)
        self.assertNotIn(password, output.getvalue())
        self.assertEqual(set(eyepqc.accounts.read_users(self.data / 'private/accounts.json')), {'first'})
        private_acl(self.data / 'private/accounts.json')

    def test_installer_default_is_program_only_and_import_is_explicit(self):
        script = (Path(__file__).resolve().parents[1] / 'installer/eyepqc.iss').read_text()
        self.assertIn('InstallationMode.SelectedValueIndex := 0', script)
        self.assertIn('if InstallationMode.SelectedValueIndex = 0 then', script)
        self.assertIn('IMPORTCURRENT', script)
        self.assertIn('SOURCECONFIG', script)
        self.assertIn('ShouldSkipPage', script)


if __name__ == '__main__':
    unittest.main()
