"""Temporary development fixtures only; never create or replace a user identity."""

import base64
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('prepare_dev_identity', ROOT / 'board/prj/prepare_dev_identity.py')
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)
import dev_usb_bootstrap as bootstrap


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'identity-fixture'

    def test_real_new_key_matches_real_pc_bootstrap_validation(self):
        record = identity.create_identity(self.output)
        public = (self.output / 'public/public.bin').read_bytes()
        pin = (self.output / 'public/public.sha256').read_text().strip()
        self.assertEqual(len(public), 800)
        self.assertEqual(pin, hashlib.sha256(public).hexdigest())
        loaded = bootstrap.private_material(self.output / 'private/board-test-identity.bin',
                                             public, bytes.fromhex(pin))
        try:
            self.assertEqual(len(loaded[:1632]), 1632)
            self.assertEqual(loaded[768:1568], public)
            self.assertEqual(loaded[1568:1600], hashlib.sha3_256(public).digest())
        finally:
            bootstrap.erase(loaded)
        self.assertEqual({path.name for path in (self.output / 'public').iterdir()},
                         {'public.bin', 'public.sha256'})
        self.assertTrue(record['development_only'])
        self.assertTrue(record['trusted_pc_required'])
        self.assertFalse(record['production_security_accepted'])
        self.assertFalse(record['keygen_seed_file_created'])
        self.assertEqual(record['user_acceptance'], 'pending')

    def test_acl_failure_precedes_randomness_key_generation_and_files(self):
        with (patch.object(identity, 'private_acl', side_effect=PermissionError('fixture')),
                patch.object(identity.os, 'urandom') as random,
                patch.object(identity.ML_KEM_512, 'key_derive') as derive):
            with self.assertRaises(PermissionError):
                identity.create_identity(self.output)
        random.assert_not_called()
        derive.assert_not_called()
        self.assertEqual(list((self.output / 'private').iterdir()), [])
        self.assertFalse((self.output / 'public').exists())

    def test_file_acl_failure_leaves_no_secret_bytes_or_randomness(self):
        original = identity.private_acl
        def acl(path, **kwargs):
            if Path(path).is_file():
                raise PermissionError('fixture file ACL')
            original(path, **kwargs)
        with patch.object(identity, 'private_acl', new=acl), patch.object(identity.os, 'urandom') as random:
            with self.assertRaises(PermissionError):
                identity.create_identity(self.output)
        random.assert_not_called()
        self.assertEqual((self.output / 'private/board-test-identity.bin').stat().st_size, 0)

    def test_existing_directory_never_overwrites_or_generates(self):
        self.output.mkdir()
        marker = self.output / 'keep'
        marker.write_bytes(b'original fixture')
        with patch.object(identity.ML_KEM_512, 'key_derive') as derive, self.assertRaises(FileExistsError):
            identity.create_identity(self.output)
        derive.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'original fixture')

    def test_rejects_relative_network_and_linked_path_before_keygen(self):
        with patch.object(identity.ML_KEM_512, 'key_derive') as derive:
            for path in ('relative-identity', r'\\server\share\identity'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    identity.create_identity(path)
            with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ValueError):
                identity.create_identity(self.output)
        derive.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_malformed_key_is_rejected_before_private_write_or_public_export(self):
        with (patch.object(identity.ML_KEM_512, 'key_derive', return_value=(bytes([7]) * 800, bytes(1632))),
                self.assertRaises(ValueError)):
            identity.create_identity(self.output)
        self.assertEqual((self.output / 'private/board-test-identity.bin').stat().st_size, 0)
        self.assertFalse((self.output / 'public').exists())

    def test_cli_output_contains_public_metadata_only(self):
        out, err = io.StringIO(), io.StringIO()
        with (patch.object(identity.os, 'urandom', return_value=bytes([0x9A]) * 64),
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
            self.assertEqual(identity.main(['--output', str(self.output)]), 0)
        key = (self.output / 'private/board-test-identity.bin').read_bytes()
        text = out.getvalue() + err.getvalue()
        self.assertNotIn(key.hex(), text)
        self.assertNotIn(base64.b64encode(key).decode(), text)
        self.assertNotIn('9a' * 64, text.lower())
        self.assertFalse(json.loads(out.getvalue())['board_accessed'])
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(identity.main(['--output', str(self.output)]), 1)
        self.assertNotIn(key.hex(), err.getvalue())

    def test_owned_buffers_erased_on_failure(self):
        erased = []
        original = identity.erase
        def erase(value):
            original(value)
            if value is not None:
                erased.append(value)
        with (patch.object(identity, 'write_new', side_effect=OSError('fixture public write failure')),
                patch.object(identity, 'erase', new=erase), self.assertRaises(OSError)):
            identity.create_identity(self.output)
        self.assertEqual({len(value) for value in erased}, {64, 1632, 1633})
        self.assertTrue(all(not any(value) for value in erased))
        self.assertFalse((self.output / 'identity.json').exists())


if __name__ == '__main__':
    unittest.main()
