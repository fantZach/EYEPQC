"""A physical-reset collector must retain the second READY and STAT."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import g0_acceptance


class ResetCapture(unittest.TestCase):
    def test_waits_for_second_stat(self):
        lines = [
            "G0 BOOT build=test boot_mode=0x05",
            "G0 DDR PASS uncached+cached", "G0 TIMER PASS interval_ms=50", "G0 READY build=test",
            "G0 STAT uptime_s=10 ticks=200 ddr_pass=2 ddr_err=0 assert=0 exception=0 timer_err=0 boot_mode=0x05",
            "G0 BOOT build=test boot_mode=0x05",
            "G0 DDR PASS uncached+cached", "G0 TIMER PASS interval_ms=50", "G0 READY build=test",
            "G0 STAT uptime_s=10 ticks=200 ddr_pass=2 ddr_err=0 assert=0 exception=0 timer_err=0 boot_mode=0x05",
        ]

        class UART:
            is_open = False

            def __init__(self, **kwargs):
                pass

            def open(self):
                self.is_open = True

            def close(self):
                self.is_open = False

            def readline(self):
                return (lines.pop(0) + "\n").encode() if lines else b""

        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(manifest=Path(directory) / "manifest.json", port="MOCK",
                                      scenario="reset_probe", seconds=100, minimum_seconds=30,
                                      reconnect_seconds=0, output=Path(directory) / "reset.jsonl")
            with patch.object(g0_acceptance, "load_manifest", return_value={"build_id": "test", "boot_bin": "mock"}), \
                 patch("serial.Serial", UART), patch("builtins.input", return_value="yes"), \
                 patch("builtins.print"), patch.object(g0_acceptance.time, "monotonic", side_effect=range(110)):
                result = g0_acceptance.capture(args)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["boot_count"], 2)
            self.assertEqual(result["stat_samples"], 2)
            saved = json.loads(args.output.with_suffix(".result.json").read_text())
            self.assertEqual(saved["status"], "passed")


if __name__ == "__main__":
    unittest.main()
