import contextlib
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/host"))
from prepare_pairing import main, prepare_pairing
from relay import read_token


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = self.root / "identity"
        self.identity.mkdir()
        self.public = bytes(range(200)) * 4
        self.pin = hashlib.sha256(self.public).hexdigest()
        (self.identity / "public.bin").write_bytes(self.public)
        (self.identity / "public.sha256").write_text(self.pin, encoding="ascii")
        self.output = self.root / "pairing"
        self.endpoint = "ws://10.179.236.247:8765/stream"

    def test_only_public_material_served_without_private_key(self):
        output = prepare_pairing(self.identity, self.endpoint, self.output)
        self.assertFalse((self.identity / "private.bin").exists())
        self.assertEqual(sorted(p.name for p in (output / "public").iterdir()),
                         ["public.bin", "public.sha256"])
        self.assertEqual((output / "public/public.bin").read_bytes(), self.public)
        token = read_token(output / "relay.token")
        pairing = (output / "pairing.txt").read_text(encoding="ascii")
        self.assertEqual(pairing, f"endpoint={self.endpoint}\ntoken={token}\npin={self.pin}\n")
        self.assertGreaterEqual(len(token), 32)
        if os.name != "nt":
            self.assertEqual((output / "relay.token").stat().st_mode & 0o777, 0o600)
            self.assertEqual((output / "pairing.txt").stat().st_mode & 0o777, 0o600)

    def test_mismatched_or_malformed_pin_rejected_before_output(self):
        for pin in ("0" * 64, "x" * 64, "1234"):
            (self.identity / "public.sha256").write_text(pin, encoding="ascii")
            with self.assertRaises(ValueError):
                prepare_pairing(self.identity, self.endpoint, self.output)
            self.assertFalse(self.output.exists())

    def test_wrong_public_size_and_missing_public(self):
        (self.identity / "public.bin").write_bytes(self.public[:-1])
        with self.assertRaises(ValueError):
            prepare_pairing(self.identity, self.endpoint, self.output)
        (self.identity / "public.bin").unlink()
        with self.assertRaises(FileNotFoundError):
            prepare_pairing(self.identity, self.endpoint, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_not_overwritten(self):
        prepare_pairing(self.identity, self.endpoint, self.output)
        before = (self.output / "relay.token").read_bytes()
        with self.assertRaises(FileExistsError):
            prepare_pairing(self.identity, self.endpoint, self.output)
        self.assertEqual((self.output / "relay.token").read_bytes(), before)

    def test_endpoint_validation(self):
        for endpoint in ("http://pc/stream", "ws://pc/other", "ws://pc:0/stream",
                         "ws://user:pass@pc/stream", "ws://pc/stream?token=abc",
                         "ws://pc/stream\n", "ws://pc:99999/stream"):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                prepare_pairing(self.identity, endpoint, self.output)
            self.assertFalse(self.output.exists())

    def test_cli_stdout_contains_paths_without_credentials(self):
        capture = io.StringIO()
        arguments = ["prepare_pairing", "--identity-dir", str(self.identity), "--endpoint",
                     self.endpoint, "--output-dir", str(self.output)]
        with patch.object(sys, "argv", arguments), contextlib.redirect_stdout(capture):
            main()
        printed = capture.getvalue()
        self.assertEqual(len(printed.splitlines()), 3)
        self.assertNotIn(read_token(self.output / "relay.token"), printed)
        self.assertNotIn(self.pin, printed)


if __name__ == "__main__":
    unittest.main()
