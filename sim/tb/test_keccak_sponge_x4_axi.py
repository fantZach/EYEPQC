"""Hashlib cross-check for the isolated stateful SHAKE128x4 AXI service."""
import hashlib
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / "src/rtl/crypto"
TB = ROOT / "sim/tb"
sys.path.insert(0, str(TB))
from iverilog_runner import compile_iverilog
from test_keccak import run_xsim


def make_vectors():
    rng = random.Random(0x584134)
    vectors = []
    for length in (0, 1, 34, 167, 168, 169):
        inputs = [bytes(rng.randrange(256) for _ in range(length)) for _ in range(4)]
        outputs = [hashlib.shake_128(data).digest(168) for data in inputs]
        vectors.append((length, inputs, outputs))
    return vectors


class KeccakSpongeX4RTL(unittest.TestCase):
    def test_axi_stateful_x4_matches_hashlib_and_guards(self):
        vectors = make_vectors()
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            vector_file = work / "vectors.txt"
            lines = [str(len(vectors))]
            for length, inputs, outputs in vectors:
                lines.append(str(length))
                lines.extend(" ".join(f"{b:02x}" for b in data) for data in inputs)
                lines.extend(" ".join(f"{b:02x}" for b in data) for data in outputs)
            vector_file.write_text("\n".join(lines) + "\n", encoding="ascii")
            exe = work / "sx4.vvp"
            iverilog = shutil.which("iverilog") or r"C:\msys64\ucrt64\bin\iverilog.exe"
            vvp = shutil.which("vvp") or r"C:\msys64\ucrt64\bin\vvp.exe"
            if not Path(iverilog).is_file() or not Path(vvp).is_file():
                self.skipTest("Icarus Verilog unavailable")
            sources = [RTL / "keccak_round.sv", RTL / "keccak_f1600.sv",
                       RTL / "keccak_sponge_x4_axi_lite.sv",
                       TB / "tb_keccak_sponge_x4_axi_lite.sv"]
            output = ""
            try:
                if os.environ.get("EYEPQC_SIMULATOR", "").lower() == "xsim":
                    raise RuntimeError("XSim selected")
                compile_iverilog([iverilog, "-g2012", "-s", "tb_keccak_sponge_x4_axi_lite",
                    "-o", str(exe), *map(str, sources)], exe)
                result = subprocess.run([vvp, str(exe), f"+VECTORS={vector_file}"],
                    capture_output=True, text=True, timeout=180)
                if result.returncode:
                    raise subprocess.CalledProcessError(result.returncode, result.args,
                        output=result.stdout, stderr=result.stderr)
                output = result.stdout
            except (RuntimeError, subprocess.CalledProcessError):
                output = run_xsim("tb_keccak_sponge_x4_axi_lite", sources,
                                  vector_file, work / "xsim")
            self.assertEqual(len(re.findall(r"KECCAK_SX4_VECTOR_PASS", output)), len(vectors), output)
            self.assertIn("KECCAK_SX4_PASS vectors=6 byte_order=little_endian stateful=1 timeout_abort=1 clear_status=0",
                          output)
            print(output.strip().splitlines()[-2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
