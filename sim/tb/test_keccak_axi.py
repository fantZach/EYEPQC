"""XSim AXI-Lite and host-driver tests for the isolated Keccak accelerator."""
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
TB = ROOT / "sim/tb"
RTL = ROOT / "board/src/rtl/crypto"
PS = ROOT / "board/src/ps/experimental"
sys.path.insert(0, str(TB))
from test_keccak import keccak_f1600, run_xsim


def state_words(lanes):
    words = []
    for lane in lanes:
        words += [lane & 0xffffffff, (lane >> 32) & 0xffffffff]
    return words


class KeccakAXI(unittest.TestCase):
    def test_axi_lite_reference_and_control(self):
        rng = random.Random(0xA71_1600)
        lanes = [rng.getrandbits(64) for _ in range(25)]
        expected = keccak_f1600(lanes)
        words = state_words(lanes) + state_words(expected)
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            vector = work / "axi_words.txt"
            vector.write_text("".join(f"{word:08x}\n" for word in words), encoding="ascii")
            output = run_xsim(
                "tb_keccak_axi_lite",
                [RTL / "keccak_round.sv", RTL / "keccak_f1600.sv",
                 RTL / "keccak_axi_lite.sv", TB / "tb_keccak_axi_lite.sv"],
                vector, work / "xsim")
        self.assertIn("KECCAK_AXI_REFERENCE_PASS", output)
        self.assertIn("KECCAK_AXI_CLEAR_PASS busy_abort=1 zeroize=1", output)
        self.assertRegex(output, r"KECCAK_AXI_PASS independent_aw_w=1 backpressure=1 errors=1 busy_guards=1 reset=1 clear=1 timeout=1")
        for line in output.splitlines():
            if "KECCAK_AXI_" in line:
                print(line)

    def test_c_driver_mock_timeout_and_fallback(self):
        gcc = shutil.which("gcc") or "C:/msys64/ucrt64/bin/gcc.exe"
        if not Path(gcc).is_file() and shutil.which("gcc") is None:
            self.skipTest("MSYS2 GCC unavailable")
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / "keccak_driver_mock.exe"
            command = [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                       f"-I{PS}", str(TB / "test_keccak_driver.c"),
                       str(PS / "keccak_accel.c"), str(PS / "mlkem_keccak_adapter.c"),
                       "-o", str(exe)]
            env = os.environ.copy()
            gcc_dir = str(Path(gcc).resolve().parent)
            msys_root = Path(gcc).resolve().parents[2]
            env["PATH"] = os.pathsep.join([gcc_dir, str(msys_root / "usr/bin"), env.get("PATH", "")])
            built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("KECCAK_DRIVER_MOCK_PASS mmio_words=50 default_off=1 id_version_guard=1 bounded_timeout_clear=1 sw_fallback=1",
                          result.stdout)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
