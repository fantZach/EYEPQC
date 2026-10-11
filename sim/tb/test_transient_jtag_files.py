"""Host-side JTAG key staging and failure-cleanup regression tests."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/host"))

import m09
import m10_board
from handshake import wipe_secret
from transient_file import staged_file


class TransientJtagFileTests(unittest.TestCase):
    def test_staged_input_is_removed_after_success(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-transient-") as temp:
            secret = bytearray(b"test-only private key bytes")
            with staged_file(temp, ".test-key-", secret) as path:
                self.assertEqual(path.read_bytes(), secret)
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])
            wipe_secret(secret)

    def test_staged_output_is_removed_after_exception(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-transient-") as temp:
            path = None
            observed_before_unlink = []
            original_unlink = Path.unlink

            def inspect_then_unlink(target, *args, **kwargs):
                if target.exists() and target.stat().st_size:
                    observed_before_unlink.append(target.read_bytes())
                return original_unlink(target, *args, **kwargs)

            with patch.object(Path, "unlink", inspect_then_unlink):
                with self.assertRaisesRegex(RuntimeError, "simulated tool failure"):
                    with staged_file(temp, ".tool-reply-") as path:
                        path.write_bytes(b"board session key response")
                        raise RuntimeError("simulated tool failure")
            self.assertFalse(path.exists())
            self.assertEqual(list(Path(temp).iterdir()), [])
            self.assertEqual(observed_before_unlink, [bytes(len(b"board session key response"))])

    def test_m10_exchange_uses_transient_key_and_reply_paths(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-m10-exchange-") as temp:
            folder = Path(temp)
            payload = bytearray(b"K" * m10_board.SK)
            paths = []

            def fake_run(call, **_kwargs):
                request_path, data_path, reply_path = map(Path, call[8:11])
                self.assertEqual(request_path.stat().st_size, 256)
                self.assertEqual(data_path.read_bytes(), payload)
                paths.extend((request_path, data_path, reply_path))
                reply_path.write_bytes(struct.pack(
                    "<8I56s44s12s32s80s", 0x30314d45, 2, 1, 0, 3, 0, 0, 0,
                    bytes(range(56)), bytes(44), bytes(12), bytes(32), bytes(80)))
                return SimpleNamespace(returncode=0, stdout="M10_JOB_DONE", stderr="")

            owned = {
                "m10_job": {"address": 0x100000, "size": 256},
                "m10_sk": {"address": 0x101000, "size": m10_board.SK},
                "m10_wire": {"address": 0x102000, "size": 972},
            }
            with patch.object(m10_board, "OUT", folder), patch.object(m10_board.subprocess, "run", fake_run):
                response = m10_board.exchange(folder, folder, owned, "load", "load", payload)
            self.assertEqual(response["material"], bytearray(range(56)))
            self.assertTrue(all(not path.exists() for path in paths))
            self.assertEqual([p.name for p in folder.iterdir()], ["load.log"])
            for field in ("material", "board_finished", "nonce", "transcript"):
                wipe_secret(response[field])
            wipe_secret(payload)

    def test_m09_failed_initial_load_still_attempts_ap0_clear(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-m09-cleanup-") as temp:
            root = Path(temp)
            out = root / "m09"
            out.mkdir()
            pk = bytes((index % 251 for index in range(m09.PK)))
            sk = bytearray((index % 239 for index in range(m09.SK)))
            sk[768:1568] = pk
            (out / "public.bin").write_bytes(pk)
            (out / "private.bin").write_bytes(sk)
            (out / "ciphertext.bin").write_bytes(bytes(m09.CT))
            (out / "expected_shared.bin").write_bytes(bytes(m09.SS))
            (out / "public.sha256").write_text(hashlib.sha256(pk).hexdigest())
            sk[:] = bytes(len(sk))

            elf, xsa = root / "test.elf", root / "test.xsa"
            elf.write_bytes(b"elf")
            xsa.write_bytes(b"xsa")
            workspace = root / "workspace"
            workspace.mkdir()
            manifest = {
                "sources": {}, "elf": str(elf), "elf_sha256": hashlib.sha256(elf.read_bytes()).hexdigest(),
                "xsa": str(xsa), "xsa_sha256": hashlib.sha256(xsa.read_bytes()).hexdigest(),
                "owned": {
                    "m09_job": {"address": 0x100000, "size": 128},
                    "m09_sk": {"address": 0x101000, "size": m09.SK},
                    "m09_ct": {"address": 0x102000, "size": m09.CT},
                },
            }
            (workspace / "build_manifest.json").write_text(json.dumps(manifest))
            kat_dir = root / "data/kat"
            kat_dir.mkdir(parents=True)
            kat_private = bytes((index % 197 for index in range(m09.SK)))
            kat_ciphertext = bytes((index % 193 for index in range(m09.CT)))
            (kat_dir / "nist_mlkem512.json").write_text(json.dumps({
                "encapsulation": [{"dk": kat_private.hex(), "c": kat_ciphertext.hex(),
                                   "k": bytes(32).hex()}]}))

            calls = []
            staged_key_paths = []

            def fake_run(call, **_kwargs):
                command = call[4]
                calls.append(command)
                if command == "load":
                    data_path, reply_path = Path(call[9]), Path(call[10])
                    self.assertEqual(data_path.read_bytes(), kat_private)
                    staged_key_paths.append(data_path)
                    return SimpleNamespace(returncode=1, stdout="", stderr="simulated load timeout")
                reply_path = Path(call[10])
                reply_path.write_bytes(struct.pack(
                    "<8I3Q32s40s", 0x39304d45, 2, 3, 0, 0, 0, 0, 0,
                    0, 0, 0, bytes(32), bytes(40)))
                return SimpleNamespace(returncode=0, stdout="M09_JOB_DONE", stderr="")

            with patch.object(m09, "ROOT", root), patch.object(m09, "OUT", out), \
                    patch.object(m09.subprocess, "run", fake_run):
                with self.assertRaisesRegex(RuntimeError, "JTAG acvp_load failed"):
                    m09.board(workspace, root)
            self.assertEqual(calls, ["load", "clear"])
            self.assertTrue(staged_key_paths and not staged_key_paths[0].exists())
            self.assertFalse(any(path.name.startswith(".acvp_load-") for path in out.iterdir()))

    def test_m10_failed_initial_load_still_attempts_ap0_clear(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-m10-cleanup-") as temp:
            root = Path(temp)
            m09_out, m10_out = root / "m09", root / "m10"
            m09_out.mkdir()
            m10_out.mkdir()
            pk = bytes((index % 251 for index in range(m10_board.PK)))
            sk = bytearray((index % 239 for index in range(m10_board.SK)))
            sk[768:1568] = pk
            (m09_out / "public.bin").write_bytes(pk)
            (m09_out / "private.bin").write_bytes(sk)
            (m09_out / "public.sha256").write_text(hashlib.sha256(pk).hexdigest())
            sk[:] = bytes(len(sk))
            lib = root / "mlkem.dll"
            lib.write_bytes(b"test")
            calls = []

            class FakeHost:
                def close(self):
                    self.closed = True

            fake_host = FakeHost()

            def fake_exchange(_workspace, _tool_root, _owned, _label, command, *_args, **_kwargs):
                calls.append(command)
                if command == "load":
                    raise RuntimeError("simulated load timeout")
                return {"zeroized": 1, "state": 4, "material": bytearray(56),
                        "board_finished": bytearray(44), "nonce": bytearray(12),
                        "transcript": bytearray(32)}

            owned = {
                "m10_job": {"address": 0x100000, "size": 256},
                "m10_sk": {"address": 0x101000, "size": m10_board.SK},
                "m10_wire": {"address": 0x102000, "size": 972},
            }
            with patch.object(m10_board, "manifest_check", return_value=owned), \
                    patch.object(m10_board, "LIB", lib), patch.object(m10_board, "OUT", m10_out), \
                    patch.object(m10_board, "M09_OUT", m09_out), patch.object(m10_board, "Kem", return_value=object()), \
                    patch.object(m10_board, "HostSession", return_value=fake_host), \
                    patch.object(m10_board, "exchange", fake_exchange):
                with self.assertRaisesRegex(RuntimeError, "simulated load timeout"):
                    m10_board.board(root, root)
            self.assertEqual(calls, ["load", "clear"])
            self.assertTrue(fake_host.closed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
