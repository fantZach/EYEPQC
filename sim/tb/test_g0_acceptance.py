import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "prj"))
from g0_acceptance import verify_log


def sample_run(scenario="sd_cold_start_30m", end=1800, extra=()):
    lines = [
        {"line": "G0 BOOT build=abc123def456 boot_mode=0x05 cpu_hz=666666687 FCLK0=100000000 UART=115200 LED=PL_H15 heartbeat_hz=1"},
        {"line": "G0 DDR PASS uncached+cached scratch=00200080 bytes=65536 full_ddr=no ddr_passes=2"},
        {"line": "G0 TIMER PASS interval_ms=50 ticks_per_second=20"},
        {"line": "G0 READY build=abc123def456 boot_mode=0x05 net_init=no usb_init=no"},
    ]
    for uptime in range(10, end + 1, 10):
        ddr = 2 + uptime // 60
        lines.append({"line": f"G0 STAT uptime_s={uptime} ticks={uptime * 20} ddr_pass={ddr} ddr_err=0 assert=0 exception=0 timer_err=0 boot_mode=0x05"})
    lines.extend(extra)
    lines.append({"event": "operator_observation", "led_1hz_seen": True,
                  "reset_pressed_once": scenario == "reset_probe",
                  "sd_card_prepared": scenario == "sd_cold_start_30m",
                  "sd_boot_straps_confirmed": scenario == "sd_cold_start_30m",
                  "cold_power_cycle_confirmed": scenario == "sd_cold_start_30m"})
    return lines


def boot_segment(end=30):
    lines = [
        {"line": "G0 BOOT build=abc123def456 boot_mode=0x05 cpu_hz=666666687 FCLK0=100000000 UART=115200 LED=PL_H15 heartbeat_hz=1"},
        {"line": "G0 DDR PASS uncached+cached scratch=00200080 bytes=65536 full_ddr=no ddr_passes=2"},
        {"line": "G0 TIMER PASS interval_ms=50 ticks_per_second=20"},
        {"line": "G0 READY build=abc123def456 boot_mode=0x05 net_init=no usb_init=no"},
    ]
    for uptime in range(10, end + 1, 10):
        ddr = 2 + uptime // 60
        lines.append({"line": f"G0 STAT uptime_s={uptime} ticks={uptime * 20} ddr_pass={ddr} ddr_err=0 assert=0 exception=0 timer_err=0 boot_mode=0x05"})
    return lines


def write_log(rows):
    temp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False)
    with temp:
        for row in rows:
            import json
            temp.write(json.dumps(row) + "\n")
    return Path(temp.name)


class G0AcceptanceTests(unittest.TestCase):
    def test_jtag_led_probe_allows_non_sd_bootmode_but_requires_fresh_led_observation(self):
        rows = sample_run(end=30, scenario="jtag_led_probe")
        for row in rows:
            if row.get("line"):
                row["line"] = row["line"].replace("boot_mode=0x05", "boot_mode=0x00")
        log = write_log(rows)
        try:
            result = verify_log(log, "jtag_led_probe", {"build_id": "abc123def456"}, 30)
            self.assertEqual(result["status"], "passed", result["failures"])
            self.assertEqual(result["boot_modes"], ["0x00"])
        finally:
            log.unlink()

    def test_sd_cold_start_30_minutes_requires_periodic_ddr_and_timer_evidence(self):
        log = write_log(sample_run())
        try:
            result = verify_log(log, "sd_cold_start_30m", {"build_id": "abc123def456"}, 1800)
            self.assertEqual(result["status"], "passed", result["failures"])
            self.assertEqual(result["final_ddr_passes"], 32)
            self.assertEqual(result["final_uptime_s"], 1800)
        finally:
            log.unlink()

    def test_reset_probe_requires_second_boot_and_operator_confirmation(self):
        rows = boot_segment(30) + boot_segment(30)
        rows.append({"event": "operator_observation", "led_1hz_seen": True,
                     "reset_pressed_once": True})
        log = write_log(rows)
        try:
            result = verify_log(log, "reset_probe", {"build_id": "abc123def456"})
            self.assertEqual(result["status"], "passed", result["failures"])
            self.assertEqual(result["boot_count"], 2)
            self.assertEqual(result["final_uptime_s"], 30)
        finally:
            log.unlink()

    def test_reset_probe_rejects_missing_second_ready_and_extra_boots(self):
        two_boots = boot_segment(30) + boot_segment(30)
        ready_index = next(i for i, row in enumerate(two_boots)
                           if row["line"].startswith("G0 READY"))
        del two_boots[ready_index]
        two_boots.append({"event": "operator_observation", "led_1hz_seen": True,
                          "reset_pressed_once": True})
        log = write_log(two_boots)
        try:
            result = verify_log(log, "reset_probe", {"build_id": "abc123def456"})
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("READY marker" in reason for reason in result["failures"]))
        finally:
            log.unlink()
        three_boots = boot_segment(30) * 3
        three_boots.append({"event": "operator_observation", "led_1hz_seen": True,
                            "reset_pressed_once": True})
        log = write_log(three_boots)
        try:
            result = verify_log(log, "reset_probe", {"build_id": "abc123def456"})
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("exactly two" in reason for reason in result["failures"]))
        finally:
            log.unlink()

    def test_fault_or_reboot_invalidates_stability_run(self):
        rows = sample_run(extra=({"line": "G0 FAIL code=2 where=DDR periodic uptime_ticks=1200"},
                                 {"line": "G0 BOOT build=abc123def456 boot_mode=0x05 cpu_hz=666666687 FCLK0=100000000 UART=115200 LED=PL_H15 heartbeat_hz=1"}))
        log = write_log(rows)
        try:
            result = verify_log(log, "sd_cold_start_30m", {"build_id": "abc123def456"}, 1800)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("target reported failure" in reason for reason in result["failures"]))
            self.assertTrue(any("application boots" in reason for reason in result["failures"]))
        finally:
            log.unlink()

    def test_uart_disconnect_and_reconnect_invalidates_evidence(self):
        rows = sample_run(extra=({"event": "uart_disconnected", "wall_utc": "test"},
                                 {"event": "uart_reconnected", "wall_utc": "test"}))
        log = write_log(rows)
        try:
            result = verify_log(log, "sd_cold_start_30m", {"build_id": "abc123def456"}, 1800)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("not continuous" in reason for reason in result["failures"]))
        finally:
            log.unlink()

    def test_wrong_boot_mode_or_missing_led_observation_fails(self):
        rows = sample_run(end=30)
        rows[0]["line"] = rows[0]["line"].replace("0x05", "0x00")
        rows[-1]["led_1hz_seen"] = False
        log = write_log(rows)
        try:
            result = verify_log(log, "sd_cold_start_30m", {"build_id": "abc123def456"}, 30)
            self.assertEqual(result["status"], "failed")
            self.assertTrue(any("not SD0" in reason for reason in result["failures"]))
            self.assertTrue(any("visually" in reason for reason in result["failures"]))
        finally:
            log.unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
