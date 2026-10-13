"""Offline debug certificate and ACL checks; no network listeners or hardware."""

import datetime as dt
import hashlib
import ipaddress
import json
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
from cryptography import x509
from cryptography.x509.oid import ExtendedKeyUsageOID
from accounts import Accounts
from prepare_test_tls import prepare, private_acl


def handshake(server, client):
    incoming, outgoing, server_in, server_out = (ssl.MemoryBIO() for _ in range(4))
    client_socket = client.wrap_bio(incoming, outgoing, server_hostname='127.0.0.1')
    server_socket = server.wrap_bio(server_in, server_out, server_side=True)
    finished = set()
    for _ in range(30):
        for index, socket in enumerate((client_socket, server_socket)):
            try:
                socket.do_handshake()
                finished.add(index)
            except ssl.SSLWantReadError:
                pass
        if outgoing.pending:
            server_in.write(outgoing.read())
        if server_out.pending:
            incoming.write(server_out.read())
        if len(finished) == 2:
            return
    raise AssertionError('offline TLS handshake did not finish')


class TestPreparation(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = self.root / 'identity'
        self.identity.mkdir()
        public = bytes(800)
        (self.identity / 'public.bin').write_bytes(public)
        (self.identity / 'public.sha256').write_text(hashlib.sha256(public).hexdigest())

    def test_certificates_acl_account_and_ca_reuse(self):
        output = self.root / 'first'
        summary = prepare(output, self.identity)
        public, private = output / 'public', output / 'private'
        ca = x509.load_pem_x509_certificate((public / 'ca.pem').read_bytes())
        leaf = x509.load_pem_x509_certificate((public / 'server-chain.pem').read_bytes())
        ca.verify_directly_issued_by(ca)
        leaf.verify_directly_issued_by(ca)
        self.assertTrue(ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertFalse(leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        self.assertTrue(ca.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign)
        self.assertFalse(leaf.extensions.get_extension_for_class(x509.KeyUsage).value.key_cert_sign)
        self.assertEqual(list(leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value),
                         [ExtendedKeyUsageOID.SERVER_AUTH])
        san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertEqual(set(san.get_values_for_type(x509.IPAddress)),
                         {ipaddress.ip_address('10.179.236.247'), ipaddress.ip_address('127.0.0.1')})
        self.assertEqual(san.get_values_for_type(x509.DNSName), ['localhost'])
        now = dt.datetime.now(dt.timezone.utc)
        self.assertLess(abs((ca.not_valid_after_utc-now).total_seconds() - 30*86400), 30)
        self.assertLess(abs((leaf.not_valid_after_utc-now).total_seconds() - 7*86400), 30)
        self.assertLessEqual(leaf.not_valid_before_utc, now)
        private_acl(private)
        for path in private.iterdir():
            private_acl(path)
        login = dict(line.split('=', 1) for line in (private / 'login.txt').read_text().splitlines())
        self.assertTrue(len(login['password']) >= 40)
        import base64
        header = 'Basic ' + base64.b64encode(('viewer:' + login['password']).encode()).decode()
        self.assertTrue(Accounts(private/'accounts.json').verify(header) == 'viewer')
        for path in public.iterdir():
            data = path.read_bytes()
            self.assertFalse(login['password'].encode() in data)
            self.assertFalse(b'PRIVATE KEY' in data)
        self.assertFalse(login['password'] in json.dumps(summary))
        config = json.loads((public / 'pairing.json').read_text())
        self.assertEqual(set(config), {'version', 'endpoint', 'public_key_hex', 'public_key_sha256'})
        before = {str(p): p.read_bytes() for p in output.rglob('*') if p.is_file()}
        with self.assertRaises(FileExistsError):
            prepare(output, self.identity)
        rotated = self.root/'rotated'
        newer = prepare(rotated, self.identity, '10.1.2.3', ca_dir=output)
        self.assertEqual(summary['ca_sha256'], newer['ca_sha256'])
        self.assertFalse((rotated/'private/ca-key.pem').exists())
        self.assertTrue(all(Path(p).read_bytes() == data for p, data in before.items()))
        replacement = x509.load_pem_x509_certificate((rotated/'public/server-chain.pem').read_bytes())
        self.assertIn(ipaddress.ip_address('10.1.2.3'),
                      replacement.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(public/'server-chain.pem', private/'server-key.pem')
        handshake(tls, ssl.create_default_context(cafile=str(public/'ca.pem')))
        wrong = self.root/'wrong'
        prepare(wrong, self.identity)
        with self.assertRaises(ssl.SSLCertVerificationError):
            handshake(tls, ssl.create_default_context(cafile=str(wrong/'public/ca.pem')))

    def test_acl_failure_stops_before_key_or_password_and_bad_identity(self):
        output = self.root/'failed'
        with patch('prepare_test_tls.private_acl', side_effect=PermissionError('fixture denied')):
            with self.assertRaises(PermissionError):
                prepare(output, self.identity)
        self.assertFalse(output.exists())
        (self.identity/'public.sha256').write_text('0'*64)
        with self.assertRaises(ValueError):
            prepare(output, self.identity)
        self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
