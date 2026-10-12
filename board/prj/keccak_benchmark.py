"""Reproducible local XSim and optional Vivado OOC entry for Keccak RTL."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synth", action="store_true", help="also run Vivado OOC synthesis")
    args = parser.parse_args()
    env = os.environ.copy()
    tool_root = Path(env.get("EYEPQC_TOOL_ROOT", "E:/fpg/2026.1")).resolve()
    env["EYEPQC_TOOL_ROOT"] = str(tool_root)
    env["EYEPQC_SIMULATOR"] = "xsim"
    test = subprocess.run([sys.executable, "-m", "unittest", "sim.tb.test_keccak", "-v"],
                          cwd=ROOT, env=env)
    if test.returncode:
        return test.returncode
    print("Host C baseline: not measured. XSim cycle counts are simulation measurements only.")
    if args.synth:
        vivado = tool_root / "Vivado/bin/vivado.bat"
        if not vivado.is_file():
            raise FileNotFoundError(f"Vivado not found: {vivado}")
        command = (f'"{vivado}" -mode batch -source board/prj/keccak_ooc.tcl '
                   f'-log build/keccak_ooc.log -journal build/keccak_ooc.jou')
        result = subprocess.run(command, cwd=ROOT, env=env, shell=True)
        return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
