"""Compile isolated experimental Keccak PS objects against the existing G6 BSP."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(r"E:\fpg\2026.1")
GCC = TOOLS / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe"
OBJDUMP = GCC.with_name("arm-none-eabi-objdump.exe")
READELF = GCC.with_name("arm-none-eabi-readelf.exe")
BSP = ROOT / "build/vitis/g6_camera_fault_20261008_final/bsp/ps7_cortexa9_0"
INCLUDE = BSP / "include"
BUILD = ROOT / "build/keccak_ps_abi"
SOURCES = [ROOT / "src/ps/experimental/keccak_accel.c",
           ROOT / "src/ps/experimental/mlkem_keccak_adapter.c"]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, log):
    result = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True)
    Path(log).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log}")
    return result.stdout + result.stderr


def main():
    for tool in (GCC, OBJDUMP, READELF):
        if not tool.is_file():
            raise SystemExit(f"required verified tool missing: {tool}")
    if not (INCLUDE / "xparameters.h").is_file():
        raise SystemExit(f"existing G6 BSP header missing: {INCLUDE / 'xparameters.h'}")
    xparameters_text = (INCLUDE / "xparameters.h").read_text(encoding="utf-8", errors="replace")
    clock = re.search(r"^#define XPAR_PS7_CORTEXA9_0_CPU_CLK_FREQ_HZ\s+(\d+)", xparameters_text, re.MULTILINE)
    if not clock:
        raise SystemExit("CPU clock macro is missing from the selected G6 BSP")
    BUILD.mkdir(parents=True, exist_ok=True)
    flags = ["-mcpu=cortex-a9", "-mfpu=vfpv3", "-mfloat-abi=hard", "-std=c11", "-O3", "-g",
             "-Wall", "-Wextra", "-Werror", "-I", str(INCLUDE), "-Isrc/ps/experimental",
             "-include", str(INCLUDE / "xparameters.h"), "-c"]
    objects = []
    for source in SOURCES:
        obj = BUILD / f"{source.stem}.o"
        run([GCC, *flags, source, "-o", obj], BUILD / f"{source.stem}.compile.log")
        run([READELF, "-h", "-A", obj], BUILD / f"{source.stem}.readelf.txt")
        run([OBJDUMP, "-d", obj], BUILD / f"{source.stem}.disassembly.txt")
        objects.append(obj)
    disassembly = (BUILD / "keccak_accel.disassembly.txt").read_text(encoding="utf-8", errors="replace")
    if "dmb" not in disassembly.lower():
        raise RuntimeError("compiled ARM driver disassembly does not contain DMB barrier")
    record = {
        "result": "ARM Cortex-A9 object compile PASS; no link, BSP edits, or hardware access",
        "compiler": str(GCC),
        "flags": flags,
        "bsp": str(BSP),
        "bsp_xparameters_sha256": sha256(INCLUDE / "xparameters.h"),
        "bsp_cpu_clock_macro_hz": int(clock.group(1)),
        "objects": {obj.name: {"path": str(obj), "sha256": sha256(obj),
                               "readelf": str(BUILD / f"{obj.stem}.readelf.txt"),
                               "disassembly": str(BUILD / f"{obj.stem}.disassembly.txt")}
                    for obj in objects},
        "barrier": "keccak_accel object contains Cortex-A9 DMB instruction",
        "abi": "see per-object readelf header/attributes; expected ELF32 ARM EABI5 hard-float VFP args",
        "limits": "independent objects only; current G6 BSP/XSA has no Keccak AXI IP or assigned address",
    }
    (BUILD / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(record["result"])
    print(f"ARM_OBJECT_REPORT={BUILD / 'result.json'}")


if __name__ == "__main__":
    main()
