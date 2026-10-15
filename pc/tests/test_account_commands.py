"""Offline account CRUD with isolated fixtures; never modify actual user data."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'src/host'
sys.path.insert(0, str(SOURCE))
import accounts
import eyepqc


def authorization(user, password):
    return 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()


class AccountCommands(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.file = self.root / 'accounts.json'
        accounts.create_account(self.file, 'initial', 'old-fixture-password')

    def command(self, *arguments, password='new-fixture-password'):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(eyepqc.getpass, 'getpass', return_value=password), contextlib.redirect_stdout(
                out), contextlib.redirect_stderr(err):
            code = eyepqc.main(['account', *arguments])
        text = out.getvalue() + err.getvalue()
        self.assertNotIn(password, text)
        return code, text

    def test_add_passwd_delete_and_snapshot_unchanged(self):
        snapshot = accounts.Accounts(self.file)
        self.assertEqual(self.command('add', '--file', str(self.file), '--username', 'second')[0], 0)
        self.assertEqual(accounts.Accounts(self.file).verify(authorization('second', 'new-fixture-password')), 'second')
        self.assertIsNone(snapshot.verify(authorization('second', 'new-fixture-password')))
        self.assertEqual(self.command('passwd', '--file', str(self.file), '--username', 'initial')[0], 0)
        self.assertIsNone(accounts.Accounts(self.file).verify(authorization('initial', 'old-fixture-password')))
        self.assertEqual(snapshot.verify(authorization('initial', 'old-fixture-password')), 'initial')
        self.assertEqual(self.command('delete', '--file', str(self.file), '--username', 'second', '--yes')[0], 0)
        self.assertEqual(set(accounts.read_users(self.file)), {'initial'})

    def test_default_accounts_file_and_list_shows_no_hash_salt(self):
        with patch.object(eyepqc.cli_settings, 'effective', return_value={'accounts_file': str(self.file)}):
            code, text = self.command('list')
            self.assertEqual(code, 0)
            self.assertEqual(text, 'initial\nACCOUNT_COUNT=1\n')
            self.assertEqual(self.command('add', '--username', 'second')[0], 0)
        for item in accounts.read_users(self.file).values():
            self.assertNotIn(item['salt'], text)
            self.assertNotIn(item['hash'], text)

    def test_refused_operations_leave_original_bytes(self):
        original = self.file.read_bytes()
        for operation, name, extra in (('add', 'initial', []), ('passwd', 'missing', []),
                                       ('delete', 'initial', []), ('delete', 'initial', ['--yes']),
                                       ('delete', 'missing', ['--yes']), ('add', 'bad:name', [])):
            code, _ = self.command(operation, '--file', str(self.file), '--username', name, *extra)
            self.assertEqual(code, 1)
            self.assertEqual(self.file.read_bytes(), original)

    def test_legacy_creation_ignores_broken_settings_and_refuses_overwrite(self):
        target = self.root / 'new.json'
        with patch.object(eyepqc.cli_settings, 'effective', side_effect=AssertionError('must not read settings')):
            self.assertEqual(self.command('--file', str(target), '--username', 'legacy')[0], 0)
            original = target.read_bytes()
            self.assertEqual(self.command('--file', str(target), '--username', 'legacy')[0], 1)
            self.assertEqual(target.read_bytes(), original)

    def test_password_confirmation_and_salt_rotation(self):
        original = self.file.read_bytes()
        old = accounts.read_users(self.file)['initial']
        with patch.object(eyepqc.getpass, 'getpass', side_effect=['a', 'b']), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(eyepqc.main(['account', 'passwd', '--file', str(self.file), '--username', 'initial']), 1)
        self.assertEqual(self.file.read_bytes(), original)
        accounts.change_account(self.file, 'passwd', 'initial', 'old-fixture-password')
        current = accounts.read_users(self.file)['initial']
        self.assertNotEqual(old['salt'], current['salt'])
        self.assertNotEqual(old['hash'], current['hash'])

    def test_strict_corrupt_duplicate_oversize_and_user_limit(self):
        entry = accounts.read_users(self.file)['initial']
        good = json.dumps({'fixture': entry})
        invalid = [b'[]', b'{}', b'\xff', b' ' * (accounts.MAX_FILE_BYTES + 1),
                   good.replace('"fixture":', '"fixture":{},"fixture":').encode(),
                   good.replace('"hash":', '"hash":"00","hash":').encode(),
                   json.dumps({'fixture': entry | {'salt': None}}).encode(),
                   json.dumps({'fixture': entry | {'salt': True}}).encode(),
                   json.dumps({'fixture': entry | {'salt': {}}}).encode(),
                   json.dumps({'fixture': entry | {'hash': '0' * 63}}).encode(),
                   json.dumps({'fixture': entry | {'hash': 'z' * 64}}).encode(),
                   json.dumps({'fixture': entry | {'password': 'never-print-secret'}}).encode(),
                   json.dumps({'fixture': {'salt': entry['salt'], 'hash': entry['hash'], 'hash2': ''}}).encode(),
                   json.dumps({str(i): entry for i in range(101)}).encode()]
        for data in invalid:
            self.file.write_bytes(data)
            with self.subTest(data=data[:15]), self.assertRaises(ValueError):
                accounts.read_users(self.file)
            self.assertEqual(self.command('add', '--file', str(self.file), '--username', 'new')[0], 1)
            self.assertEqual(self.file.read_bytes(), data)
        self.file.write_text(json.dumps({str(i): entry for i in range(100)}))
        original = self.file.read_bytes()
        self.assertEqual(self.command('add', '--file', str(self.file), '--username', 'overflow')[0], 1)
        self.assertEqual(self.file.read_bytes(), original)

    def test_atomic_failure_preserves_database_and_cleans_temporary_file(self):
        original = self.file.read_bytes()
        with patch.object(accounts.os, 'replace', side_effect=PermissionError('fixture')):
            self.assertEqual(self.command('add', '--file', str(self.file), '--username', 'new')[0], 1)
        self.assertEqual(self.file.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.accounts-*.tmp')))

    def test_create_never_overwrites_noncooperating_writer_after_exists_check(self):
        target = self.root / 'racing-create.json'
        publish_name = 'rename' if os.name == 'nt' else 'link'
        publish = getattr(accounts.os, publish_name)

        def other_writer_appears(source, destination):
            Path(destination).write_bytes(b'non-cooperating-writer-preserved')
            return publish(source, destination)

        with patch.object(accounts.os, publish_name, side_effect=other_writer_appears):
            with self.assertRaises(FileExistsError):
                accounts.create_account(target, 'new', 'fixture-password')
        self.assertEqual(target.read_bytes(), b'non-cooperating-writer-preserved')
        self.assertFalse(list(self.root.glob('.accounts-*.tmp')))

    def test_other_process_lock_rejects_writer_and_releases_normally(self):
        script = ('import sys;sys.path.insert(0,sys.argv[1]);import accounts;'
                  'accounts.change_account(sys.argv[2],"delete","initial",confirmed=True)')
        with accounts.account_lock(self.file):
            result = subprocess.run([sys.executable, '-c', script, str(SOURCE), str(self.file)],
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('account file is busy', result.stderr)
        accounts.change_account(self.file, 'add', 'second', 'fixture')
        self.assertEqual(set(accounts.read_users(self.file)), {'initial', 'second'})

    def test_new_file_add_and_invalid_length_password(self):
        new = self.root / 'add.json'
        accounts.change_account(new, 'add', 'one', 'fixture')
        self.assertEqual(set(accounts.read_users(new)), {'one'})
        for password in ('', 'x' * 1025, None, 'abc\n', 'abc\x7f', 'abc\x9f'):
            with self.assertRaises(ValueError):
                accounts.change_account(new, 'passwd', 'one', password)
        for username in ('bad\x7f', 'bad\x80', '坏' * 43):
            with self.assertRaises(ValueError):
                accounts.change_account(new, 'add', username, 'fixture')
        accounts.change_account(new, 'add', '正常', ' password with spaces 中文 ')
        self.assertEqual(accounts.Accounts(new).verify(authorization('正常', ' password with spaces 中文 ')), '正常')

    def test_install_data_cli_passes_only_source_path_and_prints_static_status(self):
        from types import SimpleNamespace
        install = unittest.mock.Mock(return_value={'private': 'never-print-fixture-secret'})
        with patch.dict(sys.modules, install_data=SimpleNamespace(install=install)), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(eyepqc.main(['install-data', '--config', str(self.root / 'legacy.json')]), 0)
        install.assert_called_once_with(self.root / 'legacy.json')
        self.assertIn('DATA_INSTALL_OK', output.getvalue())
        self.assertNotIn('never-print-fixture-secret', output.getvalue())


if __name__ == '__main__':
    unittest.main()
