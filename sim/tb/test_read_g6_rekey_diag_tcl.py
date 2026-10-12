from __future__ import annotations

from pathlib import Path
import tkinter
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "board/prj" / "read_g6_rekey_diag.tcl"
VALID_ARGS = ["0x100000", "144"]


def run_script(
    args: list[str], *, overrides: dict[int, int] | None = None,
    changed_after_read: bool = False, partial_read: bool = False,
):
    interp = tkinter.Tcl()
    output: list[str] = []
    calls = {"connect": 0, "targets": 0, "mrd": 0, "disconnect": 0, "reads": []}
    try:
        diag_addr = int(args[0], 0) if args else int(VALID_ARGS[0], 0)
    except ValueError:
        diag_addr = int(VALID_ARGS[0], 0)
    diag = [
        0x47365244, 2, 144, 2, 0, 1, 6, 2, 2, 0xFFFFFFFF,
        1, 0, 1, 1, 14, 1, 0, 17, 17, 0,
        0x20000, 0x20000, 0x12000000, 0, 0, 1, 1, 0,
        0, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF, 0,
        2,
    ]
    for index, value in (overrides or {}).items():
        diag[index] = value
    read_count = 0

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
        nonlocal read_count
        calls["mrd"] += 1
        assert mrd_args[:3] == ("-address-space", "AP0", "-value")
        address = int(mrd_args[3], 0)
        count = int(mrd_args[4])
        calls["reads"].append((address, count))
        self_read = address == diag_addr
        if self_read:
            read_count += 1
            values = diag.copy()
            if changed_after_read and read_count == 2:
                values[4] = 4
            if partial_read and read_count == 1:
                values.pop()
            return " ".join(str(word) for word in values)
        raise AssertionError("reader attempted an out-of-scope memory read")

    def puts(*args):
        output.append(" ".join(str(arg) for arg in args))
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


class ReadG6RekeyDiagTests(unittest.TestCase):
    def test_stable_snapshot_reports_only_non_sensitive_status(self):
        exit_code, output, calls = run_script(VALID_ARGS)
        self.assertEqual(exit_code, 0)
        self.assertEqual(calls["connect"], 1)
        self.assertEqual(calls["targets"], 1)
        self.assertEqual(calls["disconnect"], 1)
        self.assertEqual(calls["mrd"], 2)
        self.assertIn("phase=WAIT_HELLO phase_id=0", output)
        self.assertIn("hello_attempts=2", output)
        self.assertIn("hello_ack_send_status=ffffffff", output)
        self.assertIn("ep1_ready=00020000", output)
        self.assertIn("tx_completion_count=0", output)
        self.assertIn("tx_completion_status=ffffffff", output)
        self.assertIn("payload_or_keys=not_read", output)
        self.assertNotRegex(
            SCRIPT.read_text(encoding="utf-8"),
            r"(?im)^\s*(?:mwr|stop|rst|dow|load)\s",
        )

    def test_invalid_args_rejected_before_connect(self):
        for args in (["0x100004", "144"], ["0x3fffffc0", "144"],
                     ["0x100000", "116"], ["not-an-address", "144"],
                     ["0x100000"]):
            with self.subTest(args=args):
                exit_code, _output, calls = run_script(list(args))
                self.assertEqual(exit_code, 1)
                self.assertEqual(calls["connect"], 0)
                self.assertEqual(calls["mrd"], 0)

    def test_bad_header_phase_boolean_or_torn_snapshot_rejected(self):
        for overrides in ({0: 0}, {1: 1}, {2: 116}, {3: 3}, {4: 6},
                          {12: 2}, {16: 2048}, {29: 6}, {34: 32}):
            with self.subTest(overrides=overrides):
                exit_code, _output, calls = run_script(
                    VALID_ARGS, overrides=dict(overrides)
                )
                self.assertEqual(exit_code, 1)
                self.assertEqual(calls["mrd"], 2)

        exit_code, _output, calls = run_script(VALID_ARGS, changed_after_read=True)
        self.assertEqual(exit_code, 1)
        self.assertEqual(calls["mrd"], 2)

        exit_code, _output, calls = run_script(VALID_ARGS, partial_read=True)
        self.assertEqual(exit_code, 1)
        self.assertEqual(calls["mrd"], 1)


if __name__ == "__main__":
    unittest.main()
