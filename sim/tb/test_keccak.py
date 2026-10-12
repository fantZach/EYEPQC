"""Cross-check the standalone Keccak RTL against Python's hashlib."""
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
RTL = ROOT / "board/src/rtl/crypto"
TB = ROOT / "sim/tb"
sys.path.insert(0, str(TB))
from iverilog_runner import compile_iverilog


def executable(name, windows):
    return shutil.which(name) or (windows if Path(windows).is_file() else None)


def run_xsim(top, sources, vector_file, work):
    root = Path(os.environ.get("EYEPQC_TOOL_ROOT", "E:/fpg/2026.1")).resolve()
    settings = root / "Vivado/settings64.bat"
    if not settings.is_file():
        raise RuntimeError(f"Vivado settings not found: {settings}")
    work.mkdir(parents=True, exist_ok=True)
    xvlog_files = " ".join(f'"{Path(p).resolve()}"' for p in sources)
    commands = [
        f'call "{settings}" && xvlog -sv {xvlog_files}',
        f'call "{settings}" && xelab -debug typical {top} -s {top}_snapshot',
        f'call "{settings}" && xsim {top}_snapshot -runall -testplusarg "VECTORS={Path(vector_file).resolve().as_posix()}"',
    ]
    output = ""
    for command in commands:
        result = subprocess.run(command, cwd=work, shell=True,
                                capture_output=True, text=True, timeout=240)
        if result.returncode:
            raise RuntimeError(f"XSim command failed ({result.returncode}): {command}\n"
                               f"{result.stdout}\n{result.stderr}")
        output += result.stdout + result.stderr
    return output


def rol(x, n):
    n %= 64
    return x if n == 0 else ((x << n) | (x >> (64 - n))) & ((1 << 64) - 1)


def keccak_f1600(lanes):
    """Small independent FIPS 202 permutation reference in x+5*y lane order."""
    rc = [0x0000000000000001,0x0000000000008082,0x800000000000808a,0x8000000080008000,
          0x000000000000808b,0x0000000080000001,0x8000000080008081,0x8000000000008009,
          0x000000000000008a,0x0000000000000088,0x0000000080008009,0x000000008000000a,
          0x000000008000808b,0x800000000000008b,0x8000000000008089,0x8000000000008003,
          0x8000000000008002,0x8000000000000080,0x000000000000800a,0x800000008000000a,
          0x8000000080008081,0x8000000000008080,0x0000000080000001,0x8000000080008008]
    rho = [0,1,62,28,27,36,44,6,55,20,3,10,43,25,39,41,45,15,21,8,18,2,61,56,14]
    mask = (1 << 64) - 1
    a = list(lanes)
    for constant in rc:
        c = [a[x] ^ a[x+5] ^ a[x+10] ^ a[x+15] ^ a[x+20] for x in range(5)]
        d = [c[(x-1) % 5] ^ rol(c[(x+1) % 5], 1) for x in range(5)]
        a = [a[x+5*y] ^ d[x] for y in range(5) for x in range(5)]
        b = [0] * 25
        for y in range(5):
            for x in range(5):
                b[y + 5*((2*x + 3*y) % 5)] = rol(a[x+5*y], rho[x+5*y])
        a = [b[x+5*y] ^ ((~b[(x+1)%5+5*y]) & b[(x+2)%5+5*y]) for y in range(5) for x in range(5)]
        a[0] ^= constant
        a = [v & mask for v in a]
    return a


def state_hex(lanes):
    # A packed SV vector prints most-significant lane first; lane zero occupies
    # its least-significant 64 bits and is therefore the final token bytes.
    return "".join(f"{x:016x}" for x in reversed(lanes))


def sponge_vectors():
    rng = random.Random(0x20261008)
    vectors = []
    specs = [
        (0, hashlib.sha3_256, (0,1,135,136,137,272,400), [32]),
        (1, hashlib.sha3_512, (0,1,71,72,73,144,250), [64]),
        (2, hashlib.shake_128, (0,1,167,168,169,336,500), [1,167,168,169,340]),
        (3, hashlib.shake_256, (0,1,135,136,137,272,400), [1,135,136,137,300]),
    ]
    for mode, constructor, lengths, outputs in specs:
        for mlen in lengths:
            msg = bytes(rng.randrange(256) for _ in range(mlen))
            for olen in outputs:
                digest = constructor(msg).digest(olen) if mode >= 2 else constructor(msg).digest()
                vectors.append((mode, msg, digest))
    return vectors


class KeccakRTL(unittest.TestCase):
    def test_keccak_f1600_control_and_reference(self):
        rng = random.Random(1600)
        cases = [[rng.getrandbits(64) for _ in range(25)] for _ in range(5)]
        with tempfile.TemporaryDirectory() as td:
            work = Path(td); vectors = work / "perm.txt"; exe = work / "perm.vvp"
            vectors.write_text("".join(state_hex(s) + " " + state_hex(keccak_f1600(s)) + "\n" for s in cases))
            try:
                if os.environ.get("EYEPQC_SIMULATOR", "").lower() == "xsim":
                    raise RuntimeError("XSim selected")
                iverilog = executable("iverilog", "C:/msys64/ucrt64/bin/iverilog.exe")
                vvp = executable("vvp", "C:/msys64/ucrt64/bin/vvp.exe")
                if not (iverilog and vvp): raise RuntimeError("Icarus not found")
                compile_iverilog([iverilog, "-g2012", "-s", "tb_keccak_f1600", "-o", str(exe),
                    str(RTL / "keccak_round.sv"), str(RTL / "keccak_f1600.sv"),
                    str(TB / "tb_keccak_f1600.sv")], exe)
                result = subprocess.run([vvp, str(exe), f"+VECTORS={vectors}"], check=True,
                    capture_output=True, text=True, timeout=60)
                output = result.stdout
            except (RuntimeError, subprocess.CalledProcessError):
                output = run_xsim("tb_keccak_f1600", [RTL / "keccak_round.sv", RTL / "keccak_f1600.sv",
                    TB / "tb_keccak_f1600.sv"], vectors, work / "xsim")
            self.assertRegex(output, r"KECCAK_F1600_PASS vectors=5 cycles_per_permutation=24 busy_start_ignored=1 clear_abort=1")
            print(output.strip().splitlines()[-1])

    def test_sha3_shake_streaming_boundaries(self):
        vectors = sponge_vectors()
        with tempfile.TemporaryDirectory() as td:
            work = Path(td); vecfile = work / "sponge.txt"; exe = work / "sponge.vvp"
            lines = []
            for mode, msg, digest in vectors:
                toks = [str(mode), str(len(msg)), str(len(digest)), *[f"{b:02x}" for b in msg],
                        *[f"{b:02x}" for b in digest]]
                lines.append(" ".join(toks) + "\n")
            vecfile.write_text("".join(lines))
            try:
                if os.environ.get("EYEPQC_SIMULATOR", "").lower() == "xsim":
                    raise RuntimeError("XSim selected")
                iverilog = executable("iverilog", "C:/msys64/ucrt64/bin/iverilog.exe")
                vvp = executable("vvp", "C:/msys64/ucrt64/bin/vvp.exe")
                if not (iverilog and vvp): raise RuntimeError("Icarus not found")
                compile_iverilog([iverilog, "-g2012", "-s", "tb_keccak_sponge", "-o", str(exe),
                    str(RTL / "keccak_round.sv"), str(RTL / "keccak_f1600.sv"),
                    str(RTL / "keccak_sponge.sv"), str(TB / "tb_keccak_sponge.sv")], exe)
                output = subprocess.run([vvp, str(exe), f"+VECTORS={vecfile}"], check=True,
                    capture_output=True, text=True, timeout=180).stdout
            except (RuntimeError, subprocess.CalledProcessError):
                output = run_xsim("tb_keccak_sponge", [RTL / "keccak_round.sv", RTL / "keccak_f1600.sv",
                    RTL / "keccak_sponge.sv", TB / "tb_keccak_sponge.sv"], vecfile, work / "xsim")
            match = re.search(r"KECCAK_SPONGE_PASS vectors=(\d+)", output)
            self.assertIsNotNone(match, output)
            self.assertEqual(int(match.group(1)), len(vectors))
            marker = next(line for line in output.splitlines() if "KECCAK_SPONGE_PASS" in line)
            print(f"{marker} hashlib_cases={len(vectors)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
