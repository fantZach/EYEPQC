import unittest

from prj.parse_keccak_sponge_x4_board_benchmark import EXPECTED_CASES, WINDOWS, parse_log


def fixture() -> str:
    lines = [
        "KX41_BENCH board=not_asserted hw_compiled=1 counter_hz=333333343 vectors=60 keygen=25 encapsulation=25 decapsulation=10",
        "KX41_BENCH_VALIDATION per_vector_kat=1 identity_at_window=1",
    ]
    for window in WINDOWS:
        lines.append(f"KX41_WINDOW_START window={window}")
        if window != "software":
            lines.append(f"HARDWARE_CONTEXT_IDENTITY_PASS window={window} id=4b583431 version=00010000")
        lines.append(f"KX41_WINDOW_TICKS window={window} hi=00000000 lo=00001000")
        for operation, tcid in EXPECTED_CASES:
            lines.append(f"KX41_VECTOR_PASS window={window} operation={operation} tcId={tcid}")
        hardware = window == "hardware"
        timeout = window == "timeout_fallback"
        lines.append(
            f"KX41_WINDOW_SUMMARY window={window} vectors=60 absorbs=120 "
            f"hw_absorbs={120 if hardware or timeout else 0} "
            f"hw_squeeze_blocks={300 if hardware else 0} fallback={60 if timeout else 0} "
            f"timeout={60 if timeout else 0} error=0 timeout_status_zero_vectors={60 if timeout else 0}"
        )
    lines.extend([
        "KX41_FINAL_STATUS=00000000",
        "KX41_FINAL_STATUS_CLEAR_PASS",
        "KX41_TIMEOUT_MEMORY_READBACK=NOT_PERFORMED",
        "KX41_BENCH_DONE",
    ])
    return "\r\n".join(lines) + "\r\n"


class KX41LogParserTests(unittest.TestCase):
    def test_valid_full_60_vector_three_window_fixture(self):
        parsed = parse_log(fixture(), expected_counter_hz=333333343)
        self.assertEqual(parsed["windows"]["hardware"]["unique_vectors"], 60)
        self.assertEqual(parsed["hardware_over_software_ratio"], 1.0)

    def test_identity_hexadecimal_case_is_ignored(self):
        text = fixture().replace("id=4b583431", "id=4B583431")
        parsed = parse_log(text, expected_counter_hz=333333343)
        self.assertTrue(parsed["hardware_path_compiled"])

    def test_rejects_identity_check_after_window_timing(self):
        marker = "HARDWARE_CONTEXT_IDENTITY_PASS window=hardware id=4b583431 version=00010000\r\n"
        text = fixture().replace(marker, "", 1)
        ticks = "KX41_WINDOW_TICKS window=hardware hi=00000000 lo=00001000\r\n"
        text = text.replace(ticks, ticks + marker, 1)
        with self.assertRaisesRegex(ValueError, "not inside its window setup"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_bad_frequency_abi(self):
        with self.assertRaisesRegex(ValueError, "32-bit UART ABI"):
            parse_log(fixture().replace("333333343", "9437417530590118751"),
                      expected_counter_hz=333333343)

    def test_rejects_missing_vector(self):
        text = fixture().replace(
            "KX41_VECTOR_PASS window=hardware operation=keygen tcId=1\r\n", "")
        with self.assertRaisesRegex(ValueError, "all 60 unique expected KAT vectors"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_duplicate_vector(self):
        marker = "KX41_VECTOR_PASS window=hardware operation=keygen tcId=1\r\n"
        text = fixture().replace(marker, marker + marker, 1)
        with self.assertRaisesRegex(ValueError, "all 60 unique expected KAT vectors"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_hardware_timeout_fallback(self):
        text = fixture().replace(
            "KX41_WINDOW_SUMMARY window=hardware vectors=60 absorbs=120 hw_absorbs=120 "
            "hw_squeeze_blocks=300 fallback=0 timeout=0 error=0 timeout_status_zero_vectors=0",
            "KX41_WINDOW_SUMMARY window=hardware vectors=60 absorbs=120 hw_absorbs=120 "
            "hw_squeeze_blocks=300 fallback=0 timeout=1 error=0 timeout_status_zero_vectors=0",
        )
        with self.assertRaisesRegex(ValueError, "did not stay on hardware or had fallbacks"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_hardware_software_fallback(self):
        marker = "KX41_WINDOW_SUMMARY window=hardware vectors=60 absorbs=120 hw_absorbs=120 "
        text = fixture().replace(marker + "hw_squeeze_blocks=300 fallback=0",
                                 marker + "hw_squeeze_blocks=300 fallback=1", 1)
        with self.assertRaisesRegex(ValueError, "did not stay on hardware or had fallbacks"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_software_window_fallback(self):
        marker = "KX41_WINDOW_SUMMARY window=software vectors=60 absorbs=120 hw_absorbs=0 "
        text = fixture().replace(marker + "hw_squeeze_blocks=0 fallback=0",
                                 marker + "hw_squeeze_blocks=0 fallback=1", 1)
        with self.assertRaisesRegex(ValueError, "software reference window used hardware or a fallback"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_missing_timeout_status_clear(self):
        text = fixture().replace(
            "timeout_status_zero_vectors=60", "timeout_status_zero_vectors=59")
        with self.assertRaisesRegex(ValueError, "clear STATUS after all 60 KATs"):
            parse_log(text, expected_counter_hz=333333343)

    def test_rejects_old_identity(self):
        text = fixture().replace("id=4b583431", "id=4b434831")
        with self.assertRaisesRegex(ValueError, "ID/version"):
            parse_log(text, expected_counter_hz=333333343)


if __name__ == "__main__":
    unittest.main(verbosity=2)
