from __future__ import annotations

from pathlib import Path
import tkinter
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "prj" / "read_g6_secure_cleanup.tcl"
VALID_ARGS = [
    "0x100000", "120",
    "0x100100", "64",
    "0x100200", "64",
    "0x100300", "64",
    "0x100400", "192",
    "0x100500", "48",
    "0x100600", "48",
]
DEV_ARGS = [
    "0x154000", "1632", "0x154800", "32", "0x155000", "1632",
    "0x155800", "32", "0x156000", "8", "0x156100", "4",
]


def run_script(
    args: list[str], *, diag_overrides: dict[int, int] | None = None,
    changed_after_read: bool = False, nonzero_frame: bool = False,
    nonzero_region: str | None = None,
    partial_read_at: int | None = None,
):
    interp = tkinter.Tcl()
    output: list[str] = []
    calls = {"connect": 0, "targets": 0, "mrd": 0, "disconnect": 0, "reads": []}
    def arg_int(index: int, base: int = 10) -> int:
        try:
            return int(args[index], base)
        except (IndexError, ValueError):
            return int(VALID_ARGS[index], base)

    diag_addr = arg_int(0, 0)
    frame_addr = arg_int(2, 0)
    frame_size = arg_int(3)
    sealed_addr = arg_int(4, 0)
    sealed_size = arg_int(5)
    tx_addr = arg_int(6, 0)
    tx_size = arg_int(7)
    session_addr = arg_int(8, 0)
    session_size = arg_int(9)
    hello_addr = arg_int(10, 0)
    hello_size = arg_int(11)
    ack_addr = arg_int(12, 0)
    ack_size = arg_int(13)
    dev_values = [arg_int(i, 0 if i % 2 == 0 else 10)
                  for i in range(14, 26)] if len(args) == 26 else []
    diag = [
        0x4736434C, 6, 0, 0, 3, 0, 1, 1, 2, 0,
        frame_addr, frame_size, 0, sealed_addr, sealed_size, 0,
        0, 0, 0, 0, 1000, 1, 1, 0,
        tx_addr, tx_size, 0, 0, 1, 2,
    ]
    for index, value in (diag_overrides or {}).items():
        diag[index] = value
    diag_reads = 0

    def connect(*_args):
        calls["connect"] += 1
        return ""

    def targets(*_args):
        calls["targets"] += 1
        return ""

    def disconnect(*_args):
        calls["disconnect"] += 1
        return ""

    def mrd(*mrd_args):
        nonlocal diag_reads
        calls["mrd"] += 1
        assert mrd_args[:3] == ("-address-space", "AP0", "-value")
        address = int(mrd_args[3], 0)
        count = int(mrd_args[4])
        calls["reads"].append((address, count))
        assert 0 < count <= 4096
        if address == diag_addr:
            diag_reads += 1
            values = diag.copy()
            if changed_after_read and diag_reads == 2:
                values[1] = 5
        else:
            regions = {
                "frame": (frame_addr, frame_size),
                "sealed": (sealed_addr, sealed_size),
                "tx": (tx_addr, tx_size),
                "session": (session_addr, session_size),
                "hello": (hello_addr, hello_size),
                "ack": (ack_addr, ack_size),
            }
            if dev_values:
                regions.update({
                    "private_key": (dev_values[0], dev_values[1]),
                    "random_seed": (dev_values[2], dev_values[3]),
                    "g6_sk_load": (dev_values[4], dev_values[5]),
                    "g6_seed_load": (dev_values[6], dev_values[7]),
                    "random_counter": (dev_values[8], dev_values[9]),
                    "g6_ready": (dev_values[10], dev_values[11]),
                })
            region = next((name for name, (base, size) in regions.items()
                           if base <= address < base + size), None)
            nonzero = nonzero_frame if region == "frame" else region == nonzero_region
            values = [0xDEADBEEF if nonzero else 0] * count
        if partial_read_at == address:
            values = values[:-1]
        return " ".join(str(x) for x in values)

    def puts(*args):
        output.append(" ".join(str(x) for x in args))
        return ""

    def exit_command(code):
        interp.call("set", "::test_exit_code", str(code))
        return ""

    for name, command in {
        "connect": connect,
        "targets": targets,
        "mrd": mrd,
        "disconnect": disconnect,
        "puts": puts,
        "exit": exit_command,
    }.items():
        interp.createcommand(name, command)
    interp.call("set", "argv", tuple(args))
    text = SCRIPT.read_text(encoding="utf-8")
    assert interp.eval(f"info complete {{{text}}}") == "1"
    interp.eval(text)
    exit_code = interp.call("set", "::test_exit_code") if interp.eval(
        "info exists ::test_exit_code"
    ) == "1" else None
    return int(exit_code) if exit_code is not None else 0, "\n".join(output), calls


class ReadG6SecureCleanupTests(unittest.TestCase):
    def test_tcl_parses_and_successfully_reads_mocked_ranges_without_payload_output(self):
        exit_code, output, calls = run_script(VALID_ARGS)
        self.assertEqual(exit_code, 0)
        self.assertEqual(calls["connect"], 1)
        self.assertEqual(calls["targets"], 1)
        self.assertEqual(calls["disconnect"], 1)
        self.assertEqual(calls["mrd"], 9)
        self.assertIn(
            "G6_CLEANUP_READBACK frame_zero=1 sealed_zero=1 tx_zero=1 session_keys_zero=1 session_counters_zero=1 hello_zero=1 ack_zero=1 total_bytes=408",
            output,
        )
        self.assertIn("G6_CLEANUP_RANGE name=session_keys bytes=80 words=20 zero=1", output)
        self.assertIn("G6_CLEANUP_RANGE name=session_counters bytes=40 words=10 zero=1", output)
        self.assertIn("G6_CLEANUP_READBACK_PASS", output)
        self.assertIn("route=3", output)
        self.assertIn("dma_reset=00000000", output)
        self.assertIn("usb_ownership_eprdystatus=00000000", output)
        self.assertIn("usb_ownership_eprdy_polls=1", output)
        self.assertIn("usb_cleanup_path=2", output)
        self.assertNotIn("DEADBEEF", output)
        self.assertNotIn("3735928559", output)
        self.assertNotRegex(
            SCRIPT.read_text(encoding="utf-8"),
            r"(?im)^\s*(?:mwr|stop|rst|dow|load)\s",
        )

    def test_development_profile_reads_owned_key_ranges_without_payload_output(self):
        exit_code, output, calls = run_script(VALID_ARGS + DEV_ARGS)
        self.assertEqual(exit_code, 0)
        self.assertEqual(calls["connect"], 1)
        self.assertEqual(calls["disconnect"], 1)
        self.assertEqual(calls["mrd"], 15)
        self.assertIn("private_key_zero=1", output)
        self.assertIn("random_seed_zero=1", output)
        self.assertIn("g6_sk_load_zero=1", output)
        self.assertIn("g6_seed_load_zero=1", output)
        self.assertIn("random_counter_zero=1", output)
        self.assertIn("g6_ready_zero=1", output)
        self.assertIn("total_bytes=3748", output)
        self.assertNotIn("DEADBEEF", output)
        self.assertNotIn("3735928559", output)

    def test_invalid_args_fail_before_connecting_to_hardware(self):
        mutations = [
            lambda a: a.__setitem__(1, "108"),
            lambda a: a.__setitem__(0, "0x100004"),
            lambda a: (a.__setitem__(2, "0x3fffffc0"), a.__setitem__(3, "128")),
            lambda a: a.__setitem__(3, "1048577"),
            lambda a: a.__setitem__(3, "65"),
            lambda a: a.__setitem__(4, "0x100100"),
            lambda a: a.__setitem__(2, "not-an-address"),
            lambda a: a.__setitem__(9, "188"),
            lambda a: a.__setitem__(8, "0x100402"),
            lambda a: a.__setitem__(11, "44"),
            lambda a: a.__setitem__(12, "0x100520"),
        ]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                args = VALID_ARGS.copy()
                mutate(args)
                exit_code, _output, calls = run_script(args)
                self.assertEqual(exit_code, 1)
                self.assertEqual(calls["connect"], 0)
                self.assertEqual(calls["targets"], 0)
                self.assertEqual(calls["mrd"], 0)

        exit_code, _output, calls = run_script(VALID_ARGS[:-1])
        self.assertEqual(exit_code, 1)
        self.assertEqual(calls["connect"], 0)
        self.assertEqual(calls["mrd"], 0)

        dev_overlap = VALID_ARGS + DEV_ARGS
        dev_overlap[14] = VALID_ARGS[6]  # private-key range overlaps TX
        exit_code, _output, calls = run_script(dev_overlap)
        self.assertEqual(exit_code, 1)
        self.assertEqual(calls["connect"], 0)
        self.assertEqual(calls["mrd"], 0)

    def test_cleanup_metadata_gate_rejects_bad_values_before_range_reads(self):
        # AXI DMA: ERR_ALL 0x0770 | IRQ_ERROR 0x4000; HALTED 0x1 | IDLE 0x2.
        cases = [
            (4, 1),       # route mode must be 3
            (5, 1),       # reset must succeed
            (6, 0x40),    # status must prove halted or idle
            (7, 0x4001),  # IRQ error rejects even when halted
            (8, 0x0771),  # any ERR_ALL bit rejects even when halted
            (9, 4),       # GCM status bits 0..2 must be clear
            (16, 1), (17, 1), (18, 1), (19, 1), (23, 1),
            (12, 1), (15, 1), (26, 1),
            (27, 1), (28, 0), (29, 0), (29, 3),
        ]
        for index, value in cases:
            with self.subTest(index=index, value=value):
                exit_code, _output, calls = run_script(
                    VALID_ARGS, diag_overrides={index: value}
                )
                self.assertEqual(exit_code, 1)
                self.assertEqual(calls["mrd"], 1)  # diagnostic only

        # A diagnostic capacity mismatch must be rejected before any buffer read.
        exit_code, _output, calls = run_script(
            VALID_ARGS, diag_overrides={11: 128}
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(calls["mrd"], 1)

    def test_diag_change_and_partial_mrd_reads_fail_closed(self):
        exit_code, _output, calls = run_script(
            VALID_ARGS, changed_after_read=True
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(calls["mrd"], 9)

        exit_code, _output, calls = run_script(
            VALID_ARGS, partial_read_at=int(VALID_ARGS[2], 0)
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(calls["mrd"], 2)  # before diag, then failed frame read

    def test_large_ranges_are_read_in_bounded_chunks(self):
        args = VALID_ARGS.copy()
        args[3] = str(4096 * 4 + 64)
        args[4] = "0x104200"
        args[6] = "0x104300"
        args[8] = "0x104400"
        args[10] = "0x104500"
        args[12] = "0x104600"
        # Keep disjoint capacities and ensure the large frame range stays in DDR.
        exit_code, output, calls = run_script(args)
        self.assertEqual(exit_code, 0)
        self.assertTrue(calls["reads"])
        self.assertLessEqual(max(count for _address, count in calls["reads"]), 4096)
        self.assertEqual(sum(count for address, count in calls["reads"]
                             if int(args[2], 0) <= address < int(args[2], 0) + int(args[3])),
                         4096 + 16)
        self.assertIn("total_bytes=16792", output)

    def test_nonzero_readback_reports_only_boolean(self):
        exit_code, output, _calls = run_script(VALID_ARGS, nonzero_frame=True)
        self.assertEqual(exit_code, 1)
        self.assertIn("G6_CLEANUP_RANGE name=frame bytes=64 words=16 zero=0", output)
        self.assertNotIn("DEADBEEF", output)
        self.assertNotIn("3735928559", output)

        exit_code, output, _calls = run_script(VALID_ARGS, nonzero_region="session")
        self.assertEqual(exit_code, 1)
        self.assertIn("G6_CLEANUP_RANGE name=session_keys bytes=80 words=20 zero=0", output)
        self.assertNotIn("DEADBEEF", output)
        self.assertNotIn("3735928559", output)


if __name__ == "__main__":
    unittest.main()
