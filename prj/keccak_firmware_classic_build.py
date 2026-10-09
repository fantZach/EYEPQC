"""Build both Keccak benchmark firmware variants with classic HSI + ARM GCC."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from build_software import CPU_FLAGS, build_bsp, digest, run
from arm_startup import verify_startup

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "src/ps/experimental"
VENDOR = ROOT / "src/third_party/mlkem"
KAT = ROOT / "data/kat/nist_mlkem512.json"
DEFAULT_OUT = ROOT / "build/parallel_20261009/C/firmware_delivery"
DEFAULT_XSA = ROOT / "build/parallel_20261009/C/route4k/vivado/keccak_experiment.xsa"
TOOLS = Path(r"E:\fpg\2026.1")
APP_SOURCES = [
    "keccak_bench_firmware.c", "keccak_accel.c", "mlkem_keccak_adapter.c",
    "mlkem_fips202_backend.c", "keccak_bench_vendor_mlkem.c",
    "keccak_bench_vendor_fips202.c", "keccak_bench_vendor_ref.c",
]
APP_HEADERS = [
    "keccak_accel.h", "mlkem_keccak_adapter.h", "mlkem_fips202_backend.h",
    "mlkem_fips202_custom.h", "mlkem_full_backend_config.h",
    "mlkem_full_backend_ref_config.h",
]


def write_kat(path: Path) -> dict:
    vector = json.loads(KAT.read_text(encoding="utf-8"))["decapsulation"][0]
    arrays = {"keccak_bench_sk": bytes.fromhex(vector["dk"]),
              "keccak_bench_ct": bytes.fromhex(vector["c"]),
              "keccak_bench_ss": bytes.fromhex(vector["k"])}
    lines = ["#ifndef KECCAK_BENCH_KAT_H", "#define KECCAK_BENCH_KAT_H", "#include <stdint.h>"]
    for name, data in arrays.items():
        lines.append(f"static const uint8_t {name}[{len(data)}] = {{")
        for i in range(0, len(data), 16):
            lines.append("    " + ", ".join(f"0x{x:02x}" for x in data[i:i+16]) + ",")
        lines.append("};")
    lines.extend(["#endif", ""])
    path.write_text("\n".join(lines), encoding="ascii")
    return {"tcId": vector["tcId"], "secret_key_bytes": len(arrays["keccak_bench_sk"]),
            "ciphertext_bytes": len(arrays["keccak_bench_ct"]), "shared_secret_bytes": len(arrays["keccak_bench_ss"]),
            "expected_ss_sha256": hashlib.sha256(arrays["keccak_bench_ss"]).hexdigest()}


def build_variant(name: str, enable_hw: bool, out: Path, cpu: Path, gcc: Path,
                  vendor_root: Path, kat_info: dict) -> dict:
    app = out / name
    build = app / "build"
    include = app / "include"
    objects_dir = build / "objects"
    for path in (build, include, objects_dir):
        path.mkdir(parents=True)
    config = include / "keccak_bench_config.h"
    config.write_text("#ifndef KECCAK_BENCH_CONFIG_H\n#define KECCAK_BENCH_CONFIG_H\n"
        f"#define KECCAK_BENCH_ENABLE_HW {1 if enable_hw else 0}\n"
        "#define KECCAK_BENCH_MMIO_BASE 0x43C10000u\n#endif\n", encoding="ascii")
    kat_header = include / "keccak_bench_kat.h"
    write_kat(kat_header)
    include_dirs = [cpu / "include", include, EXPERIMENT, vendor_root,
                    vendor_root / "mlkem", vendor_root / "mlkem/src",
                    vendor_root / "mlkem/src/fips202"]
    flags = [*CPU_FLAGS, "-std=c11", "-O3", "-g", "-Wall", "-Wextra", "-Werror"]
    include_flags = [item for folder in include_dirs for item in ("-I", str(folder))]
    objects, commands = [], []
    for index, rel in enumerate(APP_SOURCES):
        source = EXPERIMENT / rel
        obj = objects_dir / f"{index}_{source.stem}.o"
        args = [gcc, *flags, *include_flags, "-c", source, "-o", obj]
        run(args, ROOT, build / f"{index}_{source.stem}.compile.log")
        commands.append({"directory": str(ROOT), "file": str(source),
                         "arguments": [str(x) for x in args]})
        objects.append(obj)
    linker = ROOT / "prj/a9_ddr.ld"
    link = [gcc, *CPU_FLAGS, "-specs=" + str(cpu / "lib/Xilinx.spec"),
            "-Wl,--defsym=_STACK_SIZE=0x8000", "-T", linker,
            "-Wl,-Map=" + str(build / (name + ".map")), "-L", cpu / "lib",
            *objects, "-Wl,--start-group", "-lxil", "-lgcc", "-lc", "-Wl,--end-group",
            "-o", build / (name + ".elf")]
    elf = build / (name + ".elf")
    run(link, ROOT, build / "link.log")
    verify_startup(build / (name + ".map"))
    gcc_bin = gcc.parent
    readelf = gcc_bin / "arm-none-eabi-readelf.exe"
    objdump = gcc_bin / "arm-none-eabi-objdump.exe"
    run([readelf, "-h", "-A", elf], ROOT, build / "readelf.txt")
    disassembly = run([objdump, "-d", elf], ROOT, build / "disassembly.txt")
    if enable_hw and "dmb" not in disassembly.lower():
        raise RuntimeError("Hardware-enabled ELF lacks the expected DMB MMIO barrier")
    (app / "compile_commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    return {"hardware_path_compiled": enable_hw,
            "hardware_gate": "enabled image requires matching XSA and Keccak ID/version check" if enable_hw else
                "MMIO disabled; no hardware address probe",
            "benchmark_kat": kat_info,
            "generated_inputs_sha256": {"keccak_bench_config.h": digest(config),
                                        "keccak_bench_kat.h": digest(kat_header)},
            "compiler_flags": flags,
            "artifacts": {"elf": {"path": f"{name}/build/{name}.elf", "sha256": digest(elf), "bytes": elf.stat().st_size},
                "map": {"path": f"{name}/build/{name}.map", "sha256": digest(build / (name + ".map"))},
                "readelf": {"path": f"{name}/build/readelf.txt", "sha256": digest(build / "readelf.txt")},
                "disassembly": {"path": f"{name}/build/disassembly.txt", "sha256": digest(build / "disassembly.txt")},
                "compile_commands": {"path": f"{name}/compile_commands.json", "sha256": digest(app / "compile_commands.json")}}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xsa", type=Path, default=DEFAULT_XSA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--tool-root", type=Path, default=TOOLS)
    parser.add_argument("--storage-relative", default="build/parallel_20261009/C/firmware_delivery")
    args = parser.parse_args()
    xsa, out, tools = args.xsa.resolve(), Path(args.out.absolute()), args.tool_root.resolve()
    if not xsa.is_file() or out.exists():
        parser.error("Completed isolated XSA and a fresh --out directory are required")
    import zipfile
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(xsa) as archive:
        sysdef = ET.fromstring(archive.read("sysdef.xml"))
        if sysdef.find("SYSTEMINFO").attrib.get("PART") != "xc7z020clg400-2":
            parser.error("Expected xc7z020clg400-2 XSA")
        bit_members = [name for name in archive.namelist() if name.lower().endswith(".bit")]
        if len(bit_members) != 1 or "ps7_init.tcl" not in archive.namelist():
            parser.error("XSA must include the implemented bitstream and matching PS initialization")
        bit_member = bit_members[0]
    out.mkdir(parents=True)
    vendor_root = out / "vendor"
    shutil.copytree(VENDOR, vendor_root / "mlkem")
    (out / "include").mkdir()
    kat_info = write_kat(out / "include/keccak_bench_kat.h")
    bsp_cpu, gcc = build_bsp(out, xsa, tools)
    xparams = bsp_cpu / "include/xparameters.h"
    text = xparams.read_text(encoding="utf-8", errors="replace")
    clock = re.search(r"^#define XPAR_PS7_CORTEXA9_0_CPU_CLK_FREQ_HZ\s+(\d+)", text, re.MULTILINE)
    if not clock:
        raise RuntimeError("Generated BSP is missing Cortex-A9 clock frequency")
    app_records = {
        "firmware_sw": build_variant("firmware_sw", False, out, bsp_cpu, gcc, vendor_root, kat_info),
        "firmware_hw": build_variant("firmware_hw", True, out, bsp_cpu, gcc, vendor_root, kat_info),
    }
    with zipfile.ZipFile(xsa) as archive:
        (out / "matching_system.bit").write_bytes(archive.read(bit_member))
        (out / "matching_ps7_init.tcl").write_bytes(archive.read("ps7_init.tcl"))
    build_inputs = {p.relative_to(out).as_posix(): digest(p) for p in (out / "bsp").rglob("*")
                    if p.is_file() and p.suffix in (".h", ".c", ".S", ".mss", ".spec")}
    vendor_inputs = {p.relative_to(VENDOR).as_posix(): digest(p) for p in VENDOR.rglob("*") if p.is_file()}
    sources = {rel: digest(ROOT / rel) for rel in [
        "prj/keccak_firmware_classic_build.py", "prj/build_software.py", "prj/generate_bsp.tcl",
        "prj/arm_startup.py", "prj/a9_ddr.ld", *[f"src/ps/experimental/{x}" for x in APP_SOURCES + APP_HEADERS],
        "data/kat/nist_mlkem512.json"]}
    record = {"result": "classic HSI/GCC builds completed offline; board_validated=false",
        "output_location_repo_relative": args.storage_relative,
        "xsa_repo_relative": "build/parallel_20261009/C/route4k/vivado/keccak_experiment.xsa",
        "xsa_sha256": digest(xsa), "target": "xc7z020clg400-2 / ps7_cortexa9_0 / standalone",
        "xsa_bit_member": bit_member,
        "cpu_clock_hz_from_new_xsa_bsp": int(clock.group(1)),
        "address_map": {"base": "0x43C10000", "range": "4 KiB", "scope": "matching route4k experimental XSA only"},
        "app_variants": app_records, "bsp_archive_sha256": digest(bsp_cpu / "lib/libxil.a"),
        "bsp_generated_inputs_sha256": build_inputs, "vendored_mlkem_inputs_sha256": vendor_inputs,
        "project_source_sha256": sources,
        "artifacts": {name: {"path": rel, "sha256": digest(out / rel)} for name, rel in {
            "matching_bitstream": "matching_system.bit", "matching_ps7_init": "matching_ps7_init.tcl"}.items()},
        "measurements": "ELFs compile only; no PS performance values exist until run on the intended board",
        "limits": ["no UART, USB, JTAG or download performed", "software/hardware timing remains unmeasured",
            "hardware ELF compiled for explicit use only; match XSA and verify ID/version before MMIO"]}
    (out / "build_manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    if digest(xsa) != record["xsa_sha256"]:
        raise RuntimeError("XSA changed during firmware build")
    print("KECCAK_FIRMWARE_CLASSIC_BUILD_PASS", out, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
