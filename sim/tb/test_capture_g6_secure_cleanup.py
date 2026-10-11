from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from prj import capture_g6_secure_cleanup as capture


OWNED = {
    "g6_secure_cleanup_diag": (0x00100000, 120),
    "g3_frame": (0x00110000, 65600),
    "g3_sealed": (0x00130000, 68096),
    "tx": (0x00150000, 1472),
    "session": (0x00151000, 192),
    "hello": (0x00152000, 48),
    "ack": (0x00153000, 48),
}


def readback_output(*, session_keys_zero: int = 1, omit_range: str | None = None) -> str:
    lines = []
    for name, size in capture.READBACK_RANGES.items():
        if name == omit_range:
            continue
        lines.append(
            f"G6_CLEANUP_RANGE name={name} bytes={size} words={size // 4} zero=1")
    total = sum(capture.READBACK_RANGES.values())
    lines.append(
        "G6_CLEANUP_READBACK frame_zero=1 sealed_zero=1 tx_zero=1 "
        f"session_keys_zero={session_keys_zero} session_counters_zero=1 "
        f"hello_zero=1 ack_zero=1 total_bytes={total} stage_before=6 "
        "stage_after=6 scope=PS_AP0_DDR_only pl_gcm_full_readback=not_proven")
    lines.append("G6_CLEANUP_READBACK_PASS")
    return "\n".join(lines)


class CaptureG6SecureCleanupTests(unittest.TestCase):
    def make_workspace(self, root: Path) -> tuple[Path, dict]:
        workspace = root / "candidate"
        build = workspace / "g6_usb" / "build"
        build.mkdir(parents=True)
        elf = build / "g6_usb.elf"
        elf.write_bytes(b"test-elf")
        manifest = {
            "security_profile": "external_provider_unvalidated",
            "board_validated": False,
            "xsa_sha256": "ab" * 32,
            "artifacts": {
                "g6_usb/build/g6_usb.elf": hashlib.sha256(elf.read_bytes()).hexdigest()
            },
            "owned": {
                name: {"address": address, "size": size}
                for name, (address, size) in OWNED.items()
            },
        }
        (workspace / "g6_usb_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        return workspace, manifest

    def test_capture_is_elf_pinned_and_emits_only_zero_status(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-secure-readback-") as temp:
            root = Path(temp)
            workspace, _manifest = self.make_workspace(root)
            tool_root = root / "tools"
            xsdb = tool_root / "Vivado" / "bin" / "xsdb.bat"
            xsdb.parent.mkdir(parents=True)
            xsdb.write_text("mock", encoding="ascii")
            prefix = root / "evidence" / "cleanup"
            mocked = SimpleNamespace(returncode=0, stdout=readback_output(), stderr="")
            with patch.object(capture.subprocess, "run", return_value=mocked) as run:
                record = capture.capture(workspace, tool_root, prefix)

            command = run.call_args.args[0]
            self.assertEqual(command[0], str(xsdb))
            self.assertEqual(len(command) - 2, 14)  # Fourteen readback ABI args.
            self.assertEqual(command[-6:], [
                "0x151000", "192", "0x152000", "48", "0x153000", "48"
            ])
            self.assertEqual(record["readback"]["ranges"]["session_keys"]["zero"], 1)
            self.assertEqual(record["build"]["xsa_sha256"], "ab" * 32)
            self.assertTrue(prefix.with_suffix(".json").is_file())
            saved = json.loads(prefix.with_suffix(".json").read_text(encoding="utf-8"))
            serialized = json.dumps(saved).lower()
            self.assertNotIn('"payload":', serialized)
            self.assertNotIn("deadbeef", serialized)
            self.assertNotIn("3735928559", serialized)
            self.assertEqual(saved["readback"]["pl_gcm_full_readback"], "not_proven")

    def test_bad_elf_hash_or_profile_fails_before_xsdb(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-secure-readback-") as temp:
            root = Path(temp)
            workspace, manifest = self.make_workspace(root)
            tool_root = root / "missing-tools"
            manifest["artifacts"]["g6_usb/build/g6_usb.elf"] = "00" * 32
            (workspace / "g6_usb_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match"):
                capture.capture(workspace, tool_root, root / "out")

            manifest["artifacts"]["g6_usb/build/g6_usb.elf"] = hashlib.sha256(
                (workspace / "g6_usb/build/g6_usb.elf").read_bytes()).hexdigest()
            manifest["security_profile"] = "development_jtag_mailbox"
            (workspace / "g6_usb_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "production profile"):
                capture.capture(workspace, tool_root, root / "out")

    def test_manifest_rejects_overlaps_and_wrong_symbol_sizes(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-secure-readback-") as temp:
            root = Path(temp)
            workspace, manifest = self.make_workspace(root)
            manifest["owned"]["ack"]["address"] = OWNED["hello"][0] + 16
            (workspace / "g6_usb_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "overlap"):
                capture.load_build_identity(workspace)

            manifest["owned"]["ack"]["address"] = OWNED["ack"][0]
            manifest["owned"]["session"]["size"] = 188
            (workspace / "g6_usb_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "owned range"):
                capture.load_build_identity(workspace)

    def test_parser_rejects_duplicate_or_conflicting_summary_records(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-secure-readback-") as temp:
            workspace, _manifest = self.make_workspace(Path(temp))
            _identity, ranges = capture.load_build_identity(workspace)
            valid = readback_output()
            summary = next(line for line in valid.splitlines()
                           if line.startswith("G6_CLEANUP_READBACK "))
            with self.assertRaisesRegex(ValueError, "successful"):
                capture.parse_readback(valid + "\n" + summary, ranges)
            with self.assertRaisesRegex(ValueError, "successful"):
                capture.parse_readback(
                    valid + "\nG6_CLEANUP_READBACK_FAIL reason=nonzero", ranges)

    def test_parser_rejects_nonzero_missing_and_overstated_evidence(self):
        with tempfile.TemporaryDirectory(prefix="eyepqc-secure-readback-") as temp:
            workspace, _manifest = self.make_workspace(Path(temp))
            _identity, ranges = capture.load_build_identity(workspace)
            with self.assertRaisesRegex(ValueError, "nonzero DDR data"):
                capture.parse_readback(readback_output(session_keys_zero=0), ranges)
            with self.assertRaisesRegex(ValueError, "omitted"):
                capture.parse_readback(readback_output(omit_range="ack"), ranges)
            with self.assertRaisesRegex(ValueError, "scope"):
                output = readback_output().replace(
                    "pl_gcm_full_readback=not_proven", "pl_gcm_full_readback=proven")
                capture.parse_readback(output, ranges)


if __name__ == "__main__":
    unittest.main()
