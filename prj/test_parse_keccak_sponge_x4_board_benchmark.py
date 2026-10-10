import unittest

from prj.parse_keccak_sponge_x4_board_benchmark import parse_log


def fixture() -> str:
    lines = [
        "KECCAK_SX4_BENCH board=not_asserted hw_compiled=1 counter_hz=333333343",
        "KECCAK_SX4_BENCH_VALIDATION per_iteration_kat=1 identity_at_configure=1",
        "HARDWARE_CONTEXT_IDENTITY_PASS id=4b583431 version=00010000",
        "software_mlkem512_decaps_3_ticks_hi=00000000_ticks_lo=00001000",
        "software_mlkem512_decaps_3 KAT_ITER_PASS iteration=0 tcId=76",
        "software_mlkem512_decaps_3 KAT_ITER_PASS iteration=1 tcId=76",
        "software_mlkem512_decaps_3 KAT_ITER_PASS iteration=2 tcId=76",
        "software_mlkem512_decaps_3 KAT_PASS iterations=3 tcId=76",
        "software_mlkem512_decaps_3 absorbs=12 hw_absorbs=0 hw_squeeze_blocks=0 fallback=0 timeout=0 error=0",
        "HARDWARE_CONTEXT_IDENTITY_PASS id=4b583431 version=00010000",
        "hardware_mlkem512_decaps_3_ticks_hi=00000000_ticks_lo=00000800",
        "hardware_mlkem512_decaps_3 KAT_ITER_PASS iteration=0 tcId=76",
        "hardware_mlkem512_decaps_3 KAT_ITER_PASS iteration=1 tcId=76",
        "hardware_mlkem512_decaps_3 KAT_ITER_PASS iteration=2 tcId=76",
        "hardware_mlkem512_decaps_3 KAT_PASS iterations=3 tcId=76",
        "hardware_mlkem512_decaps_3 absorbs=12 hw_absorbs=12 hw_squeeze_blocks=36 fallback=0 timeout=0 error=0",
        "timeout_fallback_mlkem512_decaps_3_ticks_hi=00000000_ticks_lo=00002000",
        "timeout_fallback_mlkem512_decaps_3 KAT_ITER_PASS iteration=0 tcId=76",
        "timeout_fallback_mlkem512_decaps_3 KAT_ITER_PASS iteration=1 tcId=76",
        "timeout_fallback_mlkem512_decaps_3 KAT_ITER_PASS iteration=2 tcId=76",
        "timeout_fallback_mlkem512_decaps_3 KAT_PASS iterations=3 tcId=76",
        "timeout_fallback_mlkem512_decaps_3 absorbs=12 hw_absorbs=0 hw_squeeze_blocks=0 fallback=12 timeout=12 error=0",
        "timeout_clear_status=00000000",
        "TIMEOUT_STATUS_CLEAR_PASS",
        "TIMEOUT_STATUS_ONLY_CHECK_NO_STATE_RESULT_READBACK",
        "KECCAK_SX4_BENCH_DONE",
    ]
    return "\r\n".join(lines) + "\r\n"


class KX41LogParserTests(unittest.TestCase):
    def test_valid_three_window_fixture(self):
        parsed = parse_log(fixture(), expected_counter_hz=333333343)
        self.assertEqual(parsed["windows"]["hardware_mlkem512_decaps_3"]["ticks"], 0x800)
        self.assertEqual(parsed["hardware_over_software_ratio"], 0.5)

    def test_identity_hexadecimal_case_is_ignored(self):
        text = fixture().replace("id=4b583431", "id=4B583431")
        parsed = parse_log(text, expected_counter_hz=333333343)
        self.assertEqual(parsed["hardware_path_compiled"], True)

    def test_rejects_bad_frequency_abi(self):
        with self.assertRaisesRegex(ValueError, "32-bit UART ABI"):
            parse_log(fixture().replace("333333343", "9437417530590118751"),
                      expected_counter_hz=333333343)

    def test_rejects_missing_iteration_kat(self):
        text = fixture().replace("hardware_mlkem512_decaps_3 KAT_ITER_PASS iteration=1 tcId=76\r\n", "")
        with self.assertRaisesRegex(ValueError, "each of three iterations"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_hardware_fallback_in_success_window(self):
        text = fixture().replace(
            "hardware_mlkem512_decaps_3 absorbs=12 hw_absorbs=12 hw_squeeze_blocks=36 fallback=0 timeout=0 error=0",
            "hardware_mlkem512_decaps_3 absorbs=12 hw_absorbs=12 hw_squeeze_blocks=36 fallback=1 timeout=0 error=0",
        )
        with self.assertRaisesRegex(ValueError, "entirely in hardware"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_old_identity(self):
        text = fixture().replace("id=4b583431", "id=4b434831")
        with self.assertRaisesRegex(ValueError, "ID/version"):
            parse_log(text, expected_counter_hz=333333343)


if __name__ == "__main__":
    unittest.main(verbosity=2)
