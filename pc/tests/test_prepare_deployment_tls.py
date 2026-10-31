"""Issuer preparation uses synthetic local files; never contacts a server."""
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
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import prepare_deployment_tls as deployment
import prepare_pairing
from prepare_test_tls import certificate, pem_key
from private_acl import private_acl


class DeploymentTlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'new-issuer'

    def test_new_ca_and_ip_leaf_have_no_account_or_board_identity(self):
        result = deployment.prepare(self.output, '203.0.113.10', ca_days=30, leaf_days=14)
        ca = x509.load_pem_x509_certificate((self.output / 'public/ca.pem').read_bytes())
        chain = (self.output / 'public/server-chain.pem').read_bytes()
        leaf = x509.load_pem_x509_certificate(chain)
        leaf.verify_directly_issued_by(ca)
        ca.verify_directly_issued_by(ca)
        self.assertEqual([str(x) for x in leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)], ['203.0.113.10'])
        self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH, leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
        self.assertLessEqual(leaf.not_valid_after_utc, ca.not_valid_after_utc)
        self.assertEqual(sorted(p.name for p in (self.output / 'private').iterdir()), ['ca-key.pem', 'server-key.pem'])
        self.assertEqual(sorted(p.name for p in (self.output / 'public').iterdir()), ['ca.pem', 'server-chain.pem'])
        private_acl(self.output / 'private')
        for p in (self.output / 'private').iterdir():
            private_acl(p)
        self.assertNotIn('PRIVATE KEY', json.dumps(result))
        self.assertNotIn(str(self.root), json.dumps(result))
        self.assertNotIn('password', json.dumps(result))
        self.assertEqual(result['ca_sha256'], ca.fingerprint(hashes.SHA256()).hex())

    def test_reuse_preserves_issuer_and_bounds_leaf_expiry(self):
        deployment.prepare(self.output, '203.0.113.10', ca_days=2, leaf_days=1)
        before = {str(p.relative_to(self.output)): p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        fresh = self.root / 'renewed'
        deployment.prepare(fresh, '203.0.113.11', ca_dir=self.output, leaf_days=14)
        self.assertTrue(all((self.output / name).read_bytes() == data for name, data in before.items()))
        self.assertFalse((fresh / 'private/ca-key.pem').exists())
        ca = x509.load_pem_x509_certificate((fresh / 'public/ca.pem').read_bytes())
        leaf = x509.load_pem_x509_certificate((fresh / 'public/server-chain.pem').read_bytes())
        self.assertEqual(leaf.not_valid_after_utc, ca.not_valid_after_utc)

    def test_invalid_input_and_existing_target_are_rejected_before_creation(self):
        for kwargs in ({'ip': 'not-an-ip'}, {'ip': '203.0.113.1', 'ca_days': 0},
                       {'ip': '203.0.113.1', 'leaf_days': 398}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                deployment.prepare(self.output, **kwargs)
            self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError):
            deployment.prepare(Path('relative-issuer'), '203.0.113.1')
        with self.assertRaises(FileNotFoundError):
            deployment.prepare(self.root / 'missing-parent/new', '203.0.113.1')
        self.output.mkdir()
        keep = self.output / 'keep.txt'
        keep.write_bytes(b'operator-data')
        with self.assertRaises(FileExistsError):
            deployment.prepare(self.output, '203.0.113.1')
        self.assertEqual(keep.read_bytes(), b'operator-data')

    def test_unsuitable_ca_or_mismatched_signer_never_creates_new_output(self):
        deployment.prepare(self.output, '203.0.113.1')
        private = self.output / 'private/ca-key.pem'
        original_key = private.read_bytes()
        private.write_bytes(pem_key(rsa.generate_private_key(public_exponent=65537, key_size=2048)))
        fresh = self.root / 'refused'
        with self.assertRaises(ValueError):
            deployment.prepare(fresh, '203.0.113.2', ca_dir=self.output)
        self.assertFalse(fresh.exists())
        private.write_bytes(original_key)
        key = serialization.load_pem_private_key(original_key, None)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic-unsuitable')])
        now = dt.datetime.now(dt.timezone.utc)
        for ca_flag, expires in ((False, now + dt.timedelta(days=10)), (True, now - dt.timedelta(minutes=1))):
            cert = certificate(key, name, name, key, now - dt.timedelta(days=1), expires, ca=ca_flag)
            (self.output / 'public/ca.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            with self.assertRaises(ValueError):
                deployment.prepare(fresh, '203.0.113.2', ca_dir=self.output)
            self.assertFalse(fresh.exists())

    def test_acl_or_write_failure_never_leaves_partial_credentials(self):
        with patch.object(deployment, 'private_acl', side_effect=PermissionError('fixture')):
            with self.assertRaises(PermissionError):
                deployment.prepare(self.output, '203.0.113.1')
        self.assertFalse(self.output.exists())
        with patch.object(deployment, '_new_file', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                deployment.prepare(self.output, '203.0.113.1')
        self.assertFalse(self.output.exists())
        with patch.object(prepare_pairing.os, 'fsync', side_effect=OSError('synthetic sync failure')):
            with self.assertRaises(OSError):
                deployment.prepare(self.output, '203.0.113.1')
        self.assertFalse(self.output.exists())

    def test_ca_key_usage_is_required_not_just_basic_constraints(self):
        deployment.prepare(self.output, '203.0.113.1')
        key = serialization.load_pem_private_key((self.output / 'private/ca-key.pem').read_bytes(), None)
        now = dt.datetime.now(dt.timezone.utc)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic-no-keyusage')])
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
              .serial_number(1).not_valid_before(now - dt.timedelta(minutes=1)).not_valid_after(now + dt.timedelta(days=10))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), True).sign(key, hashes.SHA256()))
        (self.output / 'public/ca.pem').write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        with self.assertRaises(ValueError):
            deployment.prepare(self.root / 'refused', '203.0.113.2', ca_dir=self.output)


if __name__ == '__main__':
    unittest.main()
