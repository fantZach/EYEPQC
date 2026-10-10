"""Meaningful parser fixtures for the isolated Keccak UART benchmark."""
import unittest
from pathlib import Path

try:
    from .parse_keccak_board_benchmark import ParseError, parse_log
except ImportError:  # Direct execution as `python prj/test_parse_keccak_board_benchmark.py`.
    from parse_keccak_board_benchmark import ParseError, parse_log


HW_TRANSCRIPT = """\
KECCAK_BENCH board=not_asserted hw_compiled=1 counter_hz=333333343
software_keccak_100_permutations_ticks_hi=00000000_ticks_lo=000f4240
software_mlkem512_decaps_3_ticks_hi=00000000_ticks_lo=003d0900
software_mlkem512_decaps_3 dispatch=96 hw=0 fallback=96
hardware_gate id=4b434831 version=00010000 expected=4b434831/00010000
mmio_transfer_50_state_write_ticks_hi=00000000_ticks_lo=00000200
mmio_transfer_50_result_read_after_done_ticks_hi=00000000_ticks_lo=00000300
mmio_transfer_50_write_50_read_excluding_permutation_ticks_hi=00000000_ticks_lo=00000500
hardware_single_permutation_including_mmio_ticks_hi=00000000_ticks_lo=000001f4
hardware_mlkem512_decaps_3_ticks_hi=00000000_ticks_lo=001e8480
hardware_mlkem512_decaps_3 dispatch=96 hw=96 fallback=0
timeout_fallback_mlkem512_decaps_3_ticks_hi=00000000_ticks_lo=003e0000
timeout_fallback_mlkem512_decaps_3 dispatch=96 hw=0 fallback=96
MMIO_TRANSFER_RESULT_READ_GATED_DONE_PASS
timeout_clear_status=00000000
TIMEOUT_STATUS_CLEAR_PASS
TIMEOUT_STATUS_ONLY_CHECK_NO_STATE_RESULT_READBACK
KECCAK_BENCH_DONE
"""

SW_TRANSCRIPT = """\
KECCAK_BENCH board=not_asserted hw_compiled=0 counter_hz=333333343
software_keccak_100_permutations_ticks_hi=00000000_ticks_lo=000f4240
software_mlkem512_decaps_3_ticks_hi=00000000_ticks_lo=003d0900
software_mlkem512_decaps_3 dispatch=96 hw=0 fallback=96
HARDWARE_NOT_COMPILED no_mmio_probe
KECCAK_BENCH_DONE
"""


class ParseKeccakBoardBenchmarkTests(unittest.TestCase):
    def test_hw_transcript_checks_paths_and_calculates_same_boot_ratio(self):
        result = parse_log(HW_TRANSCRIPT)
        comparison = result["comparison"]
        self.assertEqual(parse_log(HW_TRANSCRIPT, expected_counter_hz=333333343)["counter_hz_from_firmware"],
                         333333343)
        self.assertEqual(result["counter_hz_from_firmware"], 333333343)
        self.assertEqual(comparison["software_over_hardware_ratio"], 2.0)
        self.assertAlmostEqual(comparison["software_average_seconds"], 4_000_000 / 333_333_343 / 3)
        self.assertEqual(result["dispatch_stats"]["hardware_mlkem512_decaps_3"],
                         {"dispatch": 96, "hardware": 96, "fallback": 0})
        self.assertEqual(result["timeout_clear_status"], 0)
        self.assertIn("STATUS register only", result["timeout_clear_scope"])
        self.assertTrue(result["complete"])

    def test_sw_only_transcript_has_no_hw_comparison(self):
        result = parse_log(SW_TRANSCRIPT)
        self.assertFalse(result["hardware_path_compiled"])
        self.assertIsNone(result["comparison"])

    def test_rejects_incomplete_or_unsafe_timeout_transcript(self):
        with self.assertRaises(ParseError):
            parse_log(HW_TRANSCRIPT.replace("counter_hz=333333343", "counter_hz=0"))
        with self.assertRaises(ParseError):
            parse_log(HW_TRANSCRIPT.replace("counter_hz=333333343", "counter_hz=9437417530590118751"))
        with self.assertRaises(ParseError):
            parse_log(HW_TRANSCRIPT, expected_counter_hz=333333344)
        with self.assertRaises(ParseError):
            parse_log(HW_TRANSCRIPT.replace("timeout_clear_status=00000000", "timeout_clear_status=00000001"))
        with self.assertRaises(ParseError):
            parse_log(HW_TRANSCRIPT.replace("KECCAK_BENCH_DONE\n", ""))
        with self.assertRaises(ParseError):
            parse_log(HW_TRANSCRIPT.replace("TIMEOUT_STATUS_CLEAR_PASS", "TIMEOUT_DEVICE_ZEROIZE_PASS"))
        with self.assertRaises(ParseError):
            parse_log(HW_TRANSCRIPT.replace("_ticks_hi=00000000_ticks_lo=00000500", "_ticks_hi=00000000_ticks_lo=00000501"))

    def test_rejects_partial_counts_wrong_identity_and_zero_duration(self):
        invalid = [
            HW_TRANSCRIPT.replace("dispatch=96 hw=96 fallback=0", "dispatch=28 hw=28 fallback=0"),
            HW_TRANSCRIPT.replace("version=00010000 expected=4b434831/00010000",
                                  "version=00020000 expected=4b434831/00020000"),
            HW_TRANSCRIPT.replace("_ticks_lo=001e8480", "_ticks_lo=00000000"),
        ]
        for transcript in invalid:
            with self.subTest(transcript=transcript):
                with self.assertRaises(ParseError):
                    parse_log(transcript)

    def test_per_iteration_kat_gate_and_configuration_identity(self):
        current = HW_TRANSCRIPT.replace(
            "software_keccak_100_permutations_ticks_hi=",
            "KECCAK_BENCH_VALIDATION per_iteration_kat=1 identity_at_configure=1\n"
            "HARDWARE_CONTEXT_IDENTITY_PASS\nHARDWARE_CONTEXT_IDENTITY_PASS\n"
            "software_keccak_100_permutations_ticks_hi=")
        for label in ["software_mlkem512_decaps_3", "hardware_mlkem512_decaps_3",
                      "timeout_fallback_mlkem512_decaps_3"]:
            current = current.replace(label + " dispatch=", label + " KAT_PASS iterations=3 tcId=76\n" + label + " dispatch=")
        self.assertTrue(parse_log(current, require_iteration_kat=True)["per_iteration_kat"])
        self.assertFalse(parse_log(HW_TRANSCRIPT)["per_iteration_kat"])
        for invalid in [HW_TRANSCRIPT, current.replace("iterations=3", "iterations=2", 1),
                        current.replace("HARDWARE_CONTEXT_IDENTITY_PASS", "HARDWARE_CONTEXT_IDENTITY_FAIL", 1),
                        current.replace("hardware_mlkem512_decaps_3 KAT_PASS iterations=3 tcId=76\n", "")]:
            with self.subTest(transcript=invalid):
                with self.assertRaises(ParseError):
                    parse_log(invalid, require_iteration_kat=True)

    def test_firmware_reads_results_only_after_bounded_done_poll(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "src/ps/experimental/keccak_bench_firmware.c").read_text(encoding="utf-8")
        start = source.index("hw_write(&mmio, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_START);")
        wait = source.index("if (!wait_for_done(&mmio, POLL_LIMIT))", start)
        gated = source.index("MMIO_TRANSFER_RESULT_READ_GATED_DONE_PASS", wait)
        result_read = source.index("hw_read(&mmio, KECCAK_ACCEL_RESULT_OFFSET", gated)
        clear = source.index("hw_write(&mmio, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_CLEAR);", result_read)
        self.assertLess(start, wait)
        self.assertLess(wait, gated)
        self.assertLess(gated, result_read)
        self.assertLess(result_read, clear)
        timeout_block = source[source.index('if (!run_decaps("timeout_fallback_mlkem512_decaps_3"'):]
        self.assertIn("hw_read(&mmio, KECCAK_ACCEL_STATUS_OFFSET)", timeout_block)
        self.assertNotIn("hw_read(&mmio, KECCAK_ACCEL_STATE_OFFSET", timeout_block)
        self.assertNotIn("hw_read(&mmio, KECCAK_ACCEL_RESULT_OFFSET", timeout_block)
        self.assertNotIn("%lu", source)
        self.assertNotIn("%lx", source)


if __name__ == "__main__":
    unittest.main()
