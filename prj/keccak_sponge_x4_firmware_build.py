"""Build one KX41-enabled ARM ELF for same-boot SW/HW/timeout decapsulation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET

from arm_startup import verify_startup
from build_software import CPU_FLAGS, build_bsp, digest, run

ROOT = Path(__file__).absolute().parents[1]
EXP = ROOT / "src/ps/experimental"
VENDOR = ROOT / "src/third_party/mlkem"
KAT = ROOT / "data/kat/nist_mlkem512.json"
TOOLS = Path(r"E:\fpg\2026.1")
APP_SOURCES = [
    "keccak_sponge_x4_board_bench_firmware.c",
    "keccak_sponge_x4_board_backend.c",
    "keccak_sponge_x4_vendor_mlkem.c",
    "keccak_sponge_x4_vendor_fips202.c",
    "keccak_sponge_x4_vendor_ref.c",
    "keccak_sponge_x4_vendor_sw_keccak.c",
    "keccak_accel.c",
]
APP_HEADERS = [
    "keccak_accel.h", "keccak_sponge_x4.h", "mlkem_sponge_backend_config.h",
    "mlkem_sponge_fips202x4_custom.h", "mlkem_fips202_custom.h",
    "mlkem_full_backend_ref_config.h",
]
SNAPSHOT_FILES = [
    "prj/keccak_sponge_x4_firmware_build.py", "prj/build_software.py",
    "prj/generate_bsp.tcl", "prj/arm_startup.py", "prj/a9_ddr.ld",
    "prj/parse_keccak_sponge_x4_board_benchmark.py",
    "prj/test_parse_keccak_sponge_x4_board_benchmark.py",
    "prj/run_keccak_sponge_x4_board_benchmark.py",
    "prj/run_keccak_sponge_x4_jtag.tcl",
    "prj/keccak_sponge_x4_system_build.py", "prj/keccak_sponge_x4_system.tcl",
    "src/rtl/crypto/keccak_sponge_x4_axi_lite.sv",
    "src/rtl/crypto/keccak_f1600.sv", "src/rtl/crypto/keccak_round.sv",
    *[f"src/ps/experimental/{x}" for x in APP_SOURCES + APP_HEADERS],
    "src/ps/experimental/keccak_sponge_x4.c",
    "src/ps/experimental/mlkem_sponge_fips202x4_custom.h",
    "src/ps/experimental/mlkem_fips202_custom.h",
    "src/ps/experimental/mlkem_full_backend_config.h",
    "data/kat/nist_mlkem512.json",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_xsa(xsa: Path, xsa_manifest: Path) -> tuple[dict, str, str]:
    manifest = json.loads(xsa_manifest.read_text(encoding="utf-8"))
    if manifest.get("target") != "xc7z020clg400-2":
        raise ValueError("XSA manifest target is not xc7z020clg400-2")
    if "FAILED" in str(manifest.get("result", "")):
        raise ValueError("failed-timing XSA manifests cannot produce board firmware")
    timing = manifest.get("implemented_timing_ns", {})
    if (not timing.get("fully_routed") or timing.get("wns", -1) < 0 or
            timing.get("whs", -1) < 0 or timing.get("max_failing_endpoints", 1) != 0 or
            timing.get("min_failing_endpoints", 1) != 0):
        raise ValueError("XSA must be fully routed with nonnegative WNS/WHS and zero failing endpoints")
    if manifest.get("reports", {}).get("critical_drc_or_errors"):
        raise ValueError("XSA manifest reports DRC/errors")
    address = manifest.get("address_map", {}).get("keccak_sponge_x4_axi_lite", {})
    if (address.get("base"), address.get("id"), address.get("version")) != (
        "0x43C10000", "0x4B583431", "0x00010000"
    ):
        raise ValueError("XSA manifest does not identify the KX41 0x43C10000 register block")
    xsa_hash = sha(xsa)
    expected = manifest.get("artifacts", {}).get("vivado/keccak_sponge_x4_experiment.xsa", {}).get("sha256")
    if expected != xsa_hash:
        raise ValueError("XSA bytes do not match the supplied routed build manifest")
    with zipfile.ZipFile(xsa) as archive:
        sysdef = ET.fromstring(archive.read("sysdef.xml"))
        if sysdef.find("SYSTEMINFO").attrib.get("PART") != "xc7z020clg400-2":
            raise ValueError("XSA part mismatch")
        bits = [x for x in archive.namelist() if x.lower().endswith(".bit")]
        if len(bits) != 1 or "ps7_init.tcl" not in archive.namelist():
            raise ValueError("matching XSA bitstream/PS initialization is missing")
    return manifest, xsa_hash, bits[0]


def write_kat(path: Path) -> dict:
    vectors = json.loads(KAT.read_text(encoding="utf-8"))
    vector = next(v for v in vectors["decapsulation"] if v["tcId"] == 76)
    arrays = {"keccak_sponge_x4_bench_sk": bytes.fromhex(vector["dk"]),
              "keccak_sponge_x4_bench_ct": bytes.fromhex(vector["c"]),
              "keccak_sponge_x4_bench_ss": bytes.fromhex(vector["k"])}
    lines = ["#ifndef KECCAK_SPONGE_X4_BENCH_KAT_H",
             "#define KECCAK_SPONGE_X4_BENCH_KAT_H", "#include <stdint.h>",
             f"#define KECCAK_SX4_BENCH_KAT_TCID {vector['tcId']}u"]
    for name, data in arrays.items():
        lines.append(f"static const uint8_t {name}[{len(data)}] = {{")
        for i in range(0, len(data), 16):
            lines.append("  " + ", ".join(f"0x{x:02x}" for x in data[i:i+16]) + ",")
        lines.append("};")
    lines.extend(["#endif", ""])
    path.write_text("\n".join(lines), encoding="ascii")
    return {"tcId": 76, "secret_key_bytes": len(arrays["keccak_sponge_x4_bench_sk"]),
            "ciphertext_bytes": len(arrays["keccak_sponge_x4_bench_ct"]),
            "expected_ss_sha256": hashlib.sha256(arrays["keccak_sponge_x4_bench_ss"]).hexdigest()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--xsa", type=Path, required=True)
    ap.add_argument("--xsa-manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--storage-relative", required=True)
    ap.add_argument("--tool-root", type=Path, default=TOOLS)
    args = ap.parse_args()
    out = Path(os.path.abspath(args.out))
    xsa = Path(os.path.abspath(args.xsa))
    xsa_manifest_path = Path(os.path.abspath(args.xsa_manifest))
    tools = args.tool_root.resolve()
    if out.exists() or not xsa.is_file() or not xsa_manifest_path.is_file():
        ap.error("fresh --out plus existing routed KX41 XSA and manifest are required")

    xsa_manifest, xsa_hash, bit_member = validate_xsa(xsa, xsa_manifest_path)
    xsa_manifest_output = xsa_manifest.get("output_location_repo_relative")
    if not isinstance(xsa_manifest_output, str) or not xsa_manifest_output:
        raise ValueError("XSA manifest lacks repository-relative output location")
    xsa_repo_relative = xsa_manifest_output.rstrip("/") + "/vivado/keccak_sponge_x4_experiment.xsa"
    xsa_manifest_repo_relative = xsa_manifest_output.rstrip("/") + "/build_manifest.json"
    out.mkdir(parents=True)
    start_hashes = {rel: sha(ROOT / rel) for rel in SNAPSHOT_FILES}
    snapshot_dir = out / "source_snapshot_files"
    for rel, expected in start_hashes.items():
        src = ROOT / rel
        if sha(src) != expected:
            raise RuntimeError("source changed while capturing build snapshot: " + rel)
        target = snapshot_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
    (out / "source_snapshot.json").write_text(json.dumps({"source_sha256": start_hashes}, indent=2) + "\n",
                                              encoding="utf-8")
    vendor_root = out / "vendor/mlkem"
    shutil.copytree(VENDOR, vendor_root)
    app = out / "firmware"
    build = app / "build"
    include = app / "include"
    objects_dir = build / "objects"
    for directory in (build, include, objects_dir):
        directory.mkdir(parents=True)
    cfg = include / "keccak_sponge_x4_bench_config.h"
    cfg.write_text("#ifndef KECCAK_SPONGE_X4_BENCH_CONFIG_H\n"
        "#define KECCAK_SPONGE_X4_BENCH_CONFIG_H\n"
        "#define KECCAK_SX4_BENCH_MMIO_BASE 0x43C10000u\n#endif\n", encoding="ascii")
    kat = include / "keccak_sponge_x4_bench_kat.h"
    kat_info = write_kat(kat)
    cpu, gcc = build_bsp(out, xsa, tools)
    xparams = (cpu / "include/xparameters.h").read_text(encoding="utf-8", errors="replace")
    clock = __import__("re").search(
        r"^#define XPAR_PS7_CORTEXA9_0_CPU_CLK_FREQ_HZ\s+(\d+)", xparams, __import__("re").M)
    if not clock:
        raise RuntimeError("BSP lacks Cortex-A9 clock frequency")
    include_dirs = [cpu / "include", include, EXP, out / "vendor",
                    vendor_root, vendor_root / "src", vendor_root / "src/fips202"]
    flags = [*CPU_FLAGS, "-std=c11", "-O3", "-g", "-Wall", "-Wextra", "-Werror"]
    inc = [item for folder in include_dirs for item in ("-I", str(folder))]
    objects, commands = [], []
    for index, rel in enumerate(APP_SOURCES):
        source = EXP / rel
        obj = objects_dir / f"{index}_{source.stem}.o"
        args_cc = [gcc, *flags, *inc, "-c", source, "-o", obj]
        run(args_cc, ROOT, build / f"{index}_{source.stem}.compile.log")
        commands.append({"directory": str(ROOT), "file": str(source),
                         "arguments": [str(x) for x in args_cc]})
        objects.append(obj)
    linker = ROOT / "prj/a9_ddr.ld"
    elf = build / "keccak_sponge_x4_board_bench.elf"
    link = [gcc, *CPU_FLAGS, "-specs=" + str(cpu / "lib/Xilinx.spec"),
            "-Wl,--defsym=_STACK_SIZE=0x8000", "-T", linker,
            "-Wl,-Map=" + str(build / "keccak_sponge_x4_board_bench.map"),
            "-L", cpu / "lib", *objects, "-Wl,--start-group", "-lxil", "-lgcc", "-lc",
            "-Wl,--end-group", "-o", elf]
    run(link, ROOT, build / "link.log")
    verify_startup(build / "keccak_sponge_x4_board_bench.map")
    gcc_bin = gcc.parent
    run([gcc_bin / "arm-none-eabi-readelf.exe", "-h", "-A", elf], ROOT, build / "readelf.txt")
    disasm = run([gcc_bin / "arm-none-eabi-objdump.exe", "-d", elf], ROOT, build / "disassembly.txt")
    if "dmb" not in disasm.lower():
        raise RuntimeError("ELF does not contain the MMIO memory barrier")
    (app / "compile_commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(xsa) as archive:
        (out / "matching_system.bit").write_bytes(archive.read(bit_member))
        (out / "matching_ps7_init.tcl").write_bytes(archive.read("ps7_init.tcl"))
    vendor_inputs = {p.relative_to(VENDOR).as_posix(): sha(p) for p in VENDOR.rglob("*") if p.is_file()}
    source_inputs = {rel: sha(ROOT / rel) for rel in SNAPSHOT_FILES}
    if source_inputs != start_hashes:
        raise RuntimeError("build inputs changed after start snapshot")
    build_inputs = {p.relative_to(out).as_posix(): sha(p) for p in (out / "bsp").rglob("*")
                    if p.is_file() and p.suffix in (".h", ".c", ".S", ".mss", ".spec")}
    record = {
        "result": "KX41 firmware built offline; no board validation",
        "output_location_repo_relative": args.storage_relative,
        "xsa_repo_relative": xsa_repo_relative,
        "xsa_sha256": xsa_hash,
        "xsa_manifest_repo_relative": xsa_manifest_repo_relative,
        "xsa_manifest_sha256": sha(xsa_manifest_path),
        "xsa_build_source_sha256": xsa_manifest.get("source_sha256", {}),
        "xsa_timing_gate": xsa_manifest["implemented_timing_ns"],
        "target": "xc7z020clg400-2 / ps7_cortexa9_0 / standalone",
        "bit_member": bit_member,
        "cpu_clock_hz_from_new_xsa_bsp": int(clock.group(1)),
        "address_map": {"module": "keccak_sponge_x4_axi_lite", "base": "0x43C10000",
            "range": "4 KiB", "id": "0x4B583431", "version": "0x00010000"},
        "measurement_scope": "one hardware-enabled ELF; software, KX41 MMIO, and forced-timeout fallback each run three tcId 76 Decaps in one boot; every output is checked",
        "kat": kat_info,
        "firmware": {"elf": {"path": "firmware/build/keccak_sponge_x4_board_bench.elf",
                    "sha256": sha(elf), "bytes": elf.stat().st_size},
            "map_sha256": sha(build / "keccak_sponge_x4_board_bench.map"),
            "readelf_sha256": sha(build / "readelf.txt"),
            "disassembly_sha256": sha(build / "disassembly.txt"),
            "compile_commands_sha256": sha(app / "compile_commands.json"),
            "compiler_flags": flags},
        "bsp_archive_sha256": sha(cpu / "lib/libxil.a"),
        "bsp_generated_inputs_sha256": build_inputs,
        "vendored_mlkem_inputs_sha256": vendor_inputs,
        "project_source_sha256": source_inputs,
        "source_snapshot_files": "source_snapshot_files/ (byte-for-byte build-start snapshot)",
        "generated_inputs_sha256": {cfg.name: sha(cfg), kat.name: sha(kat)},
        "matching_artifacts": {"bitstream_sha256": sha(out / "matching_system.bit"),
                               "ps7_init_sha256": sha(out / "matching_ps7_init.tcl")},
        "limits": ["ELF build is not a board run", "no JTAG/UART was accessed by this builder",
                   "hardware use requires this exact matching XSA and ID/version gate"],
    }
    (out / "build_manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("KECCAK_SX4_FIRMWARE_BUILD_PASS", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
