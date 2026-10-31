"""Synthetic certificate migration; never touches actual AppData, ports or credentials."""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import install_renewed_tls as renewal
import cli_settings
from prepare_test_tls import certificate, pem_key


class RenewalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, LOCALAPPDATA=str(self.root / 'user'))
        self.env.start(); self.addCleanup(self.env.stop)
        self.settings = cli_settings.settings_path()
        self.settings.parent.mkdir(parents=True)
        self.config = cli_settings.defaults()
        self.settings.write_text(json.dumps(self.config))
        self.original = self.settings.read_bytes()
        self.source = self.root / 'source'
        (self.source / 'private').mkdir(parents=True)
        (self.source / 'public').mkdir()
        now = dt.datetime.now(dt.timezone.utc)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'fixture issuer')])
        ca = certificate(key, name, name, key, now, now + dt.timedelta(days=2), ca=True)
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        import ipaddress
        self.leaf = certificate(leaf_key, name, name, key, now, now + dt.timedelta(days=1), ca=False,
                                ips=[ipaddress.IPv4Address('124.70.38.245')])
        self.chain = self.leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM)
        (self.source / 'public/server-chain.pem').write_bytes(self.chain)
        (self.source / 'private/server-key.pem').write_bytes(pem_key(leaf_key))
        for target, value in (('LEAF_PIN', self.leaf.fingerprint(hashes.SHA256()).hex()),
                              ('CA_PIN', ca.fingerprint(hashes.SHA256()).hex())):
            p = patch.object(renewal, target, value); p.start(); self.addCleanup(p.stop)
        self.acl = patch.object(renewal, 'private_acl').start()
        self.stopped = patch.object(renewal, 'ensure_stopped').start()
        self.addCleanup(patch.stopall)
        self.output = self.settings.parent / renewal.TARGET

    def test_only_tls_paths_change_and_known_files_copied(self):
        result = renewal.install(self.source)
        self.assertEqual(result['status'], 'APP_TLS_RENEWAL_INSTALLED')
        actual = cli_settings.effective()
        self.assertTrue(all(actual[k] == self.config[k] for k in self.config if k not in ('tls_cert', 'tls_key')))
        self.assertEqual((self.output / 'private/settings.before-renewal.json').read_bytes(), self.original)
        self.assertEqual(sorted(p.name for p in (self.output / 'private').iterdir()), ['server-key.pem', 'settings.before-renewal.json'])
        self.assertEqual((self.output / 'public/server-chain.pem').read_bytes(), self.chain)
        self.assertFalse(result['services_started'])
        with self.assertRaises(FileExistsError):
            renewal.install(self.source)

    def test_bad_pin_or_expired_certificate_changes_nothing(self):
        with patch.object(renewal, 'LEAF_PIN', '0' * 64), self.assertRaises(ValueError):
            renewal.install(self.source)
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)
        class Future:
            @staticmethod
            def now(zone):
                return future
        with patch.object(renewal.dt, 'datetime', Future), self.assertRaises(ValueError):
            renewal.install(self.source)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.settings.read_bytes(), self.original)

    def test_private_acl_fails_before_destination_key_write(self):
        def acl(path, **kwargs):
            if kwargs.get('protect'):
                raise PermissionError('fixture')
        self.acl.side_effect = acl
        with self.assertRaises(PermissionError):
            renewal.install(self.source)
        self.assertFalse((self.output / 'private/server-key.pem').exists())
        self.assertEqual(self.settings.read_bytes(), self.original)

    def test_service_or_concurrent_writer_blocks_commit(self):
        self.stopped.side_effect = OSError('fixture listener')
        with self.assertRaises(OSError):
            renewal.install(self.source)
        self.assertFalse(self.output.exists())
        self.stopped.side_effect = None
        changed = b'{"operator":"new-state"}'
        def concurrently():
            if self.output.exists():
                self.settings.write_bytes(changed)
        self.stopped.side_effect = concurrently
        with self.assertRaises(ValueError):
            renewal.install(self.source)
        self.assertEqual(self.settings.read_bytes(), changed)

    def test_redirected_target_relative_source_and_private_chain_rejected(self):
        redirected = self.root / 'Packages/OpenAI.Codex_fixture/LocalCache/Local/EYEPQC/pc/settings.json'
        with patch.object(cli_settings, 'settings_path', return_value=redirected), self.assertRaises(ValueError):
            renewal.install(self.source)
        with self.assertRaises(ValueError):
            renewal.install(Path('relative'))
        (self.source / 'public/server-chain.pem').write_bytes(self.chain + b'-----BEGIN PRIVATE KEY-----\nfixture\n')
        with self.assertRaises(ValueError):
            renewal.install(self.source)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
