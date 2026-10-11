from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "capture_g6_rekey_diag", ROOT / "prj/capture_g6_rekey_diag.py")
capture_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture_tool)


SNAPSHOT = """G6_REKEY_DIAG abi=2 sequence=4 phase=WAIT_HELLO phase_id=0 last_control_type=0 received_controls=0 hello_attempts=2 hello_ack_send_attempts=2 hello_ack_send_status=00000000 cleanup_count=1 cleanup_last_result=00000000 usb_configured=1 usb_dtr=1 connection_epoch=14 tx_ready=1 rx_bytes_buffered=0 rx_head=0 rx_tail=0 rx_bad=0 ep1_prime=00000000 ep1_ready=00000000 epcr1=00000000 ep1_completion=00000000 ep1_flush=00000000 control_errors=0 fatal_errors=0 transport_errors=0 tx_completion_count=1 tx_completion_status=00000000 tx_completion_token=00000000 tx_completion_residual=0 tx_completion_requested=39 tx_completion_expected=39 tx_completion_match_flags=0000001f scope=PS_AP0_DDR_diagnostic_only payload_or_keys=not_read
G6_REKEY_DIAG_READ_OK
"""


class G6RekeyDiagnosticCaptureTests(unittest.TestCase):
    def test_parser_requires_stable_metadata_only_snapshot(self) -> None:
        parsed = capture_tool.parse_snapshot(SNAPSHOT)
        self.assertEqual(parsed["hello_attempts"], 2)
        self.assertEqual(parsed["hello_ack_send_status"], 0)
        self.assertEqual(parsed["tx_completion_requested"], 39)
        self.assertEqual(parsed["tx_completion_match_flags"], 31)
        self.assertEqual(parsed["phase"], "WAIT_HELLO")
        self.assertEqual(parsed["payload_or_keys"], "not_read")
        with self.assertRaisesRegex(ValueError, "complete"):
            capture_tool.parse_snapshot(SNAPSHOT.replace("G6_REKEY_DIAG_READ_OK", ""))
        with self.assertRaisesRegex(ValueError, "phase name"):
            capture_tool.parse_snapshot(SNAPSHOT.replace("phase_id=0", "phase_id=1"))

    def test_capture_is_build_pinned_and_writes_sanitized_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eyepqc-rekey-diag-") as temp:
            root = Path(temp)
            workspace = root / "workspace"
            elf = workspace / "g6_usb/build/g6_usb.elf"
            elf.parent.mkdir(parents=True)
            elf.write_bytes(b"pinned elf bytes")
            elf_hash = hashlib.sha256(elf.read_bytes()).hexdigest()
            manifest = {
                "artifacts": {"g6_usb/build/g6_usb.elf": elf_hash},
                "xsa_sha256": "a" * 64,
                "owned": {"g6_rekey_diagnostic": {"address": 0x01000000, "size": 144}},
            }
            (workspace / "g6_usb_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            tool_root = root / "tools"
            xsdb = tool_root / "Vivado/bin/xsdb.bat"
            xsdb.parent.mkdir(parents=True)
            xsdb.write_text("mock", encoding="utf-8")
            output_prefix = root / "trial_before"
            result = mock.Mock(returncode=0, stdout=SNAPSHOT, stderr="")
            with mock.patch.object(capture_tool.subprocess, "run", return_value=result) as run:
                record = capture_tool.capture(workspace, tool_root, output_prefix)
            self.assertEqual(record["diagnostic"]["hello_attempts"], 2)
            self.assertEqual(record["size"], 144)
            self.assertTrue(output_prefix.with_suffix(".stdout.log").is_file())
            saved = json.loads(output_prefix.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertNotIn("private_key", saved)
            command = run.call_args.args[0]
            self.assertEqual(command[-2:], ["0x1000000", "144"])

    def test_manifest_range_and_elf_hash_are_required(self) -> None:
        with tempfile.TemporaryDirectory(prefix="eyepqc-rekey-manifest-") as temp:
            workspace = Path(temp)
            elf = workspace / "g6_usb/build/g6_usb.elf"
            elf.parent.mkdir(parents=True)
            elf.write_bytes(b"elf")
            manifest = {
                "artifacts": {"g6_usb/build/g6_usb.elf": "0" * 64},
                "xsa_sha256": "a" * 64,
                "owned": {"g6_rekey_diagnostic": {"address": 0x01000000, "size": 144}},
            }
            (workspace / "g6_usb_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "ELF does not match"):
                capture_tool.load_build_identity(workspace)


if __name__ == "__main__":
    unittest.main()
