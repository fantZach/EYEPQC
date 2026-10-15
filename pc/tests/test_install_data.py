"""Offline migration with synthetic material and isolated LOCALAPPDATA only."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import cli_settings
import install_data
from private_acl import private_acl


class InstallDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'offline-installer-fixture')])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(1).not_valid_before(now - dt.timedelta(minutes=1))
                .not_valid_after(now + dt.timedelta(days=1)).sign(key, hashes.SHA256()))
        cls.certificate = cert.public_bytes(serialization.Encoding.PEM)
        cls.key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            private_acl(root, protect=True)
            result = subprocess.run(['ssh-keygen', '-t', 'ed25519', '-N', '', '-f', str(root / 'identity')],
                                    capture_output=True, timeout=15)
            if result.returncode:
                raise RuntimeError('offline fixture key generation failed')
            cls.ssh_key = (root / 'identity').read_bytes()
            cls.known_hosts = b'[localhost]:2222 ' + (root / 'identity.pub').read_bytes()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'user'))
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.source = self.root / 'source'
        (self.source / 'private').mkdir(parents=True)
        (self.source / 'public').mkdir()
        private_acl(self.source / 'private', protect=True)
        self.record = cli_settings.normalize(cli_settings.default_record(), self.source)
        public = bytes(800)
        data = {
            'accounts_file': json.dumps({'fixture': {'salt': '00' * 16, 'hash': '00' * 32}}).encode(),
            'pairing_file': json.dumps(dict(version=2, endpoint='wss://localhost:8765/stream',
                public_key_hex=public.hex(), public_key_sha256=hashlib.sha256(public).hexdigest())).encode(),
            'tls_cert': self.certificate, 'tls_key': self.key,
            'tunnel.identity_file': self.ssh_key, 'tunnel.known_hosts': self.known_hosts}
        for key, _, _ in install_data.MATERIALS:
            Path(install_data.value(self.record, key)).write_bytes(data[key])
        for name in ('ca-key.pem', 'login.txt', 'board-seed.bin'):
            (self.source / 'private' / name).write_bytes(b'forbidden synthetic extra')
        self.config = self.source / 'old.json'
        self.config.write_text(json.dumps(self.record))

    def destination(self):
        return cli_settings.settings_path().parent / 'data'

    def test_managed_import_copies_only_six_files_and_preserves_sources(self):
        cli_settings.persist(self.record)
        before = {path: path.read_bytes() for path in self.source.rglob('*') if path.is_file()}
        summary = install_data.install()
        self.assertFalse(summary['already_installed'])
        self.assertEqual(sum(path.is_file() for path in self.destination().rglob('*')), 6)
        for key, relative, _ in install_data.MATERIALS:
            self.assertEqual((self.destination() / relative).read_bytes(), before[Path(install_data.value(self.record, key))])
            self.assertEqual(install_data.value(cli_settings.effective(), key), str(self.destination() / relative))
        self.assertTrue(all(path.read_bytes() == data for path, data in before.items()))
        self.assertNotIn('PRIVATE KEY', json.dumps(summary))
        self.assertNotIn('forbidden', json.dumps(summary))

    def test_explicit_legacy_configuration_resolves_relative_paths(self):
        legacy = cli_settings.default_record()
        del legacy['tunnel']['enabled']
        self.config.write_text(json.dumps(legacy))
        install_data.install(self.config)
        self.assertTrue(Path(cli_settings.effective()['tls_key']).is_file())

    def test_missing_corrupt_oversized_inputs_create_no_data(self):
        for key, _, maximum in install_data.MATERIALS:
            path = Path(install_data.value(self.record, key))
            original = path.read_bytes()
            for data in (b'', b'invalid fixture', b'x' * (maximum + 1)):
                with self.subTest(key=key, size=len(data)):
                    path.write_bytes(data)
                    with self.assertRaises((OSError, ValueError)):
                        install_data.install(self.config)
                    self.assertFalse(self.destination().exists())
                    self.assertFalse(cli_settings.settings_path().exists())
            path.write_bytes(original)

    def test_bad_config_types_fail_cleanly(self):
        for value in (None, [], 1, {'tunnel': []}, self.record | {'tunnel': 'invalid'},
                      self.record | {'tunnel': False}):
            self.config.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                install_data.install(self.config)
            self.assertFalse(self.destination().exists())

    def test_existing_data_never_overwrites_maintained_accounts(self):
        install_data.install(self.config)
        account = self.destination() / 'private/accounts.json'
        account.write_text(json.dumps({'new-user': {'salt': '01' * 16, 'hash': '02' * 32}}))
        before = account.read_bytes()
        settings = cli_settings.settings_path().read_bytes()
        self.assertTrue(install_data.install()['already_installed'])
        self.assertEqual(account.read_bytes(), before)
        self.assertEqual(cli_settings.settings_path().read_bytes(), settings)
        with self.assertRaises(FileExistsError):
            install_data.install(self.config)
        self.assertEqual(account.read_bytes(), before)

    def test_partial_existing_data_and_corrupt_settings_preserved(self):
        self.destination().mkdir(parents=True)
        marker = self.destination() / 'keep.txt'
        marker.write_text('keep')
        with self.assertRaises(ValueError):
            install_data.install(self.config)
        self.assertEqual(marker.read_text(), 'keep')
        cli_settings.settings_path().write_text('{broken')
        with self.assertRaises(ValueError):
            install_data.install(self.config)
        self.assertEqual(cli_settings.settings_path().read_text(), '{broken')

    def test_acl_failure_happens_before_any_private_file(self):
        with patch.object(install_data, 'private_acl', side_effect=PermissionError('synthetic')):
            with self.assertRaises(PermissionError):
                install_data.install(self.config)
        self.assertFalse(self.destination().exists())
        self.assertFalse(cli_settings.settings_path().exists())

    def test_settings_commit_failure_rolls_back_new_files_and_preserves_original(self):
        cli_settings.persist(self.record)
        original = cli_settings.settings_path().read_bytes()
        with patch.object(cli_settings.os, 'replace', side_effect=PermissionError('synthetic')):
            with self.assertRaises(PermissionError):
                install_data.install()
        self.assertFalse(self.destination().exists())
        self.assertEqual(cli_settings.settings_path().read_bytes(), original)

    def test_destination_write_failure_and_readback_failure_roll_back(self):
        real_open = install_data.os.open
        def fail_public(path, flags, *args, **kwargs):
            if Path(path).name == 'pairing.json':
                raise PermissionError('synthetic')
            return real_open(path, flags, *args, **kwargs)
        with patch.object(install_data.os, 'open', fail_public):
            with self.assertRaises(PermissionError):
                install_data.install(self.config)
        self.assertFalse(self.destination().exists())
        with patch.object(Path, 'read_bytes', return_value=b'wrong readback'):
            with self.assertRaises(OSError):
                install_data.install(self.config)
        self.assertFalse(self.destination().exists())

    def test_private_acl_is_restricted_and_rechecked_on_upgrade(self):
        install_data.install(self.config)
        private_acl(self.destination() / 'private')
        for name in ('accounts.json', 'server-key.pem', 'id_ed25519'):
            private_acl(self.destination() / 'private' / name)
        with patch.object(install_data, 'private_acl', side_effect=PermissionError('unsafe existing ACL')):
            with self.assertRaises(PermissionError):
                install_data.install()

    def test_reparse_point_destination_rejected(self):
        self.destination().parent.mkdir(parents=True)
        other = self.root / 'other'
        other.mkdir()
        if os.name == 'nt':
            result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(self.destination()), str(other)],
                                    capture_output=True)
            self.assertEqual(result.returncode, 0)
        else:
            self.destination().symlink_to(other, target_is_directory=True)
        try:
            with self.assertRaises(ValueError):
                install_data.install(self.config)
            self.assertEqual(list(other.iterdir()), [])
        finally:
            self.destination().rmdir() if os.name == 'nt' else self.destination().unlink()

    def test_defaults_point_to_current_user_data_not_executable_or_cwd(self):
        config = cli_settings.defaults()
        for key, relative, _ in install_data.MATERIALS:
            self.assertEqual(install_data.value(config, key), str(self.destination() / relative))

    def test_installer_is_offline_non_admin_and_preserves_data(self):
        pc = Path(__file__).resolve().parents[1]
        builder = (pc / 'build_installer.ps1').read_text(encoding='utf-8')
        script = (pc / 'installer/eyepqc.iss').read_text(encoding='utf-8')
        for forbidden in ('Invoke-WebRequest', 'WebClient', 'PrepareCompiler', 'Start-Process', 'InstallDependencies'):
            self.assertNotIn(forbidden, builder)
        self.assertIn('Get-AuthenticodeSignature', builder)
        for required in ('PrivilegesRequired=lowest', 'CloseApplications=no', 'RestartApplications=no',
                         'UsePreviousAppDir=no', 'PrepareToInstall', 'install-data',
                         'ChangesEnvironment=yes', '#include "user_path.iss"',
                         'AppId={{BC45B197-2603-498A-B857-C58A97E11DC0}',
                         'AppId={{9B9AF3F4-737E-48FD-B6A3-6B0A82BA6A7D}'):
            self.assertIn(required, script)
        self.assertNotIn('[UninstallDelete]', script)
        self.assertNotIn('[Run]', script)


if __name__ == '__main__':
    unittest.main()
