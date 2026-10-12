"""Run Keccak/SHA3 reference checks, AXI-Lite XSim, C MMIO mock, and optional OOC synthesis."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def run(command, env):
    return subprocess.run(command, cwd=ROOT, env=env).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synth", action="store_true", help="also run isolated Vivado OOC synthesis")
    args = parser.parse_args()
    env = os.environ.copy()
    tool_root = Path(env.get("EYEPQC_TOOL_ROOT", "E:/fpg/2026.1")).resolve()
    env["EYEPQC_TOOL_ROOT"] = str(tool_root)
    env["EYEPQC_SIMULATOR"] = "xsim"
    if run([sys.executable, "-m", "unittest", "sim.tb.test_keccak",
            "sim.tb.test_keccak_axi", "-v"], env):
        return 1
    print("Host C measurement not performed. XSim cycles are simulation results, not board timing.")
    if not args.synth:
        return 0
    vivado = tool_root / "Vivado/bin/vivado.bat"
    if not vivado.is_file():
        raise FileNotFoundError(f"Vivado not found: {vivado}")
    command = f'"{vivado}" -mode batch -source board/prj/keccak_axi_ooc.tcl -log build/keccak_axi_ooc.log -journal build/keccak_axi_ooc.jou'
    return subprocess.run(command, cwd=ROOT, env=env, shell=True).returncode


if __name__ == "__main__":
    raise SystemExit(main())
