"""Build a network-independent M01 G0 application and matching SD BOOT.BIN.

Offline only: requires a completed M01 XSA and never accesses a board or card.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
G0_SCRATCH_BYTES = 16384 * 4
sys.path.insert(0, str(ROOT / "board/prj"))
from arm_startup import verify_startup
from build_software import CPU_FLAGS, build_boot_images, build_bsp, run


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xsa", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--implemented-evidence", type=Path, required=True,
                        help="prefix of fresh Vivado post-implementation report files")
    parser.add_argument("--reuse-bsp", type=Path,
                        help="reuse an already generated BSP/FSBL source workspace during C iteration")
    parser.add_argument("--tool-root", type=Path,
                        default=os.environ.get("EYEPQC_TOOL_ROOT", "E:/fpg/2026.1"))
    args = parser.parse_args()
    xsa, workspace, tools = args.xsa.resolve(), args.output.resolve(), args.tool_root.resolve()
    gcc = tools / "Vitis/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe"
    for required in (xsa, tools / "Vivado/bin/xsdb.bat", tools / "Vivado/bin/bootgen.bat", gcc):
        if not required.is_file():
            parser.error(f"required input/tool not found: {required}")
    if workspace.exists():
        parser.error(f"use a fresh output directory: {workspace}")
    workspace.mkdir(parents=True)
    source_manifest_path = args.source_manifest.resolve()
    source_hashes = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    for relative, expected_hash in source_hashes.items():
        if digest(ROOT / relative) != expected_hash:
            parser.error("G0 source snapshot does not match current source: " + relative)
    evidence_prefix = args.implemented_evidence.resolve()
    implemented_summary = Path(str(evidence_prefix) + ".verified.txt")
    implemented_io = evidence_prefix
    implemented_clocks = Path(str(evidence_prefix) + ".clocks.txt")
    if not all(path.is_file() for path in (implemented_summary, implemented_io, implemented_clocks)):
        parser.error("fresh Vivado implemented I/O/clock evidence is missing")
    summary = implemented_summary.read_text(encoding="utf-8", errors="replace")
    required_summary = ("G0_IMPLEMENTED_OK", "led_PACKAGE_PIN=H15",
                        "led_IOSTANDARD=LVCMOS33", "heartbeat_clock_period_ns=10.0")
    if any(item not in summary for item in required_summary):
        parser.error("Vivado implementation evidence does not prove H15/LVCMOS33/100 MHz")

    with zipfile.ZipFile(xsa) as archive:
        system = ET.fromstring(archive.read("sysdef.xml"))
        if system.find("SYSTEMINFO").attrib.get("PART") != "xc7z020clg400-2":
            parser.error("expected xc7z020clg400-2 XSA")
        needed = {"m01.bit", "ps7_init.tcl", "ps7_init.c", "ps7_init.h", "system.hwh"}
        if not needed.issubset(set(archive.namelist())):
            parser.error("XSA must include its bitstream and PS initialization sources")
        hwh = ET.fromstring(archive.read("system.hwh"))
        parameters = {node.attrib.get("NAME"): node.attrib.get("VALUE")
                      for node in hwh.findall(".//PARAMETER")}
        if parameters.get("PCW_SD0_PERIPHERAL_ENABLE") != "1":
            parser.error("XSA hardware handoff does not enable SD0; refusing SD BOOT.BIN")
        if parameters.get("PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ") != "100.000000":
            parser.error("XSA FCLK0 is not 100 MHz; heartbeat timing assumptions changed")
        led = hwh.find(".//EXTERNALPORTS/PORT[@NAME='led']")
        if led is None or led.find("./CONNECTIONS/CONNECTION[@INSTANCE='heartbeat_0'][@PORT='led']") is None:
            parser.error("XSA has no HWH LED output connected to the heartbeat module")
        fclk = hwh.find(".//MODULES/MODULE/PORTS/PORT[@NAME='FCLK_CLK0']")
        if (fclk is None or fclk.attrib.get("CLKFREQUENCY") != "100000000" or
                fclk.find("./CONNECTIONS/CONNECTION[@INSTANCE='heartbeat_0'][@PORT='clk']") is None):
            parser.error("XSA external FCLK_CLK0 does not connect 100 MHz to the heartbeat module")

    if args.reuse_bsp:
        bsp_workspace = args.reuse_bsp.resolve()
        cpu = bsp_workspace / "bsp/ps7_cortexa9_0"
        source_fsbl = bsp_workspace / "fsbl"
        if not (cpu / "include/xparameters.h").is_file() or not (cpu / "lib/libxil.a").is_file():
            parser.error("reuse BSP workspace is missing generated headers/library")
        if not source_fsbl.is_dir():
            parser.error("reuse BSP workspace is missing generated FSBL sources")
        shutil.copytree(source_fsbl, workspace / "fsbl")
        gcc = tools / "Vitis/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe"
        print(f"G0_BSP_REUSED {bsp_workspace}")
    else:
        cpu, gcc = build_bsp(workspace, xsa, tools, boot_images=True)
    fsbl_sources = list((workspace / "fsbl").glob("*.c"))
    if not any("InitSD" in p.read_text(encoding="utf-8", errors="replace") for p in fsbl_sources):
        raise RuntimeError("generated matching FSBL has no InitSD symbol/source")

    app_name = "g0_startup"
    app = workspace / app_name
    build = app / "build"
    build.mkdir(parents=True)
    (app / "_ide/bitstream").mkdir(parents=True)
    (app / "_ide/psinit").mkdir(parents=True)
    with zipfile.ZipFile(xsa) as archive:
        for source_name, target in (("m01.bit", app / "_ide/bitstream/m01.bit"),
                                    ("ps7_init.tcl", app / "_ide/psinit/ps7_init.tcl")):
            target.write_bytes(archive.read(source_name))

    source = ROOT / "board/src/ps/src/m01_g0.c"
    source_hash = digest(source)
    xsa_hash = digest(xsa)
    build_id = hashlib.sha256((source_hash + xsa_hash).encode()).hexdigest()[:12]
    build_id_header = build / "g0_build_id.h"
    build_id_header.write_text(f'#define G0_BUILD_ID "{build_id}"\n', encoding="ascii")
    include = [cpu / "include", build]
    obj = build / "m01_g0.o"
    flags = [*CPU_FLAGS, "-std=c11", "-O3", "-g", "-Wall", "-Wextra", "-Werror"]
    compile_command = [gcc, *flags, "-include", build_id_header,
                       *[arg for p in include for arg in ("-I", p)],
                       "-c", source, "-o", obj]
    (build / "compile_command.json").write_text(
        json.dumps([str(item) for item in compile_command], indent=2) + "\n", encoding="utf-8")
    run(compile_command, ROOT, build / "compile.log")
    elf = build / f"{app_name}.elf"
    linker = ROOT / "board/prj/a9_ddr.ld"
    link_command = [gcc, *CPU_FLAGS, "-specs=" + str(cpu / "lib/Xilinx.spec"),
                    "-Wl,--defsym=_STACK_SIZE=0x8000", "-T", linker,
                    "-Wl,-Map=" + str(build / f"{app_name}.map"), "-L", cpu / "lib",
                    obj, "-Wl,--start-group", "-lxil", "-lgcc", "-lc",
                    "-Wl,--end-group", "-o", elf]
    run(link_command, ROOT, build / "link.log")
    verify_startup(build / f"{app_name}.map")
    run([gcc.with_name("arm-none-eabi-readelf.exe"), "-h", elf], ROOT,
        build / "elf_header.txt")
    nm_exe = gcc.with_name("arm-none-eabi-nm.exe")
    nm_output = run([nm_exe, "-S", elf], ROOT, build / "symbols.log")
    nm = {}
    for line in nm_output.splitlines():
        fields = line.split()
        if len(fields) == 4:
            nm[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
        elif len(fields) == 3:
            nm[fields[2]] = (int(fields[0], 16), 0)
    expected = {"scratch": G0_SCRATCH_BYTES, "__bss_start": 0, "__bss_end": 0,
                "_heap_start": 0, "_heap_end": 0, "_stack_end": 0, "_stack": 0, "_end": 0}
    if any(name not in nm for name in expected):
        raise RuntimeError("ELF is missing DDR scratch/section boundary symbols")
    scratch_address, scratch_size = nm["scratch"]
    bss_start, bss_end = nm["__bss_start"][0], nm["__bss_end"][0]
    heap_start, heap_end = nm["_heap_start"][0], nm["_heap_end"][0]
    stack_end, stack_top, image_end = nm["_stack_end"][0], nm["_stack"][0], nm["_end"][0]
    if (scratch_size != G0_SCRATCH_BYTES or scratch_address % 64 or
            not bss_start <= scratch_address < scratch_address + scratch_size <= bss_end <=
            heap_start <= heap_end <= stack_end <= stack_top <= image_end <= 0x40000000 or
            bss_start < 0x00100000):
        raise RuntimeError("G0 scratch/BSS/heap/stack layout overlaps or exceeds DDR bounds")
    (build / "link_command.json").write_text(
        json.dumps([str(item) for item in link_command], indent=2) + "\n", encoding="utf-8")

    interface_files = [cpu / "include" / name for name in
                       ("xparameters.h", "xparameters_ps.h", "bspconfig.h", "xtime_l.h",
                        "xscutimer.h", "xscugic.h", "xinterrupt_wrap.h")]
    for driver, filename in (("scutimer_v2_8", "xscutimer_g.c"),
                             ("scugic_v5_7", "xscugic_g.c"),
                             ("standalone_v9_5", "xinterrupt_wrap.c")):
        matches = list((cpu / "libsrc" / driver / "src").glob(filename))
        if not matches:
            raise RuntimeError(f"generated BSP is missing interface source {driver}/{filename}")
        interface_files.extend(matches)
    if any(not path.is_file() for path in interface_files):
        raise RuntimeError("generated BSP is missing a header used by the G0 interrupt ABI")

    build_boot_images(workspace, cpu, gcc, tools, [app_name], xsa)
    boot = app / "boot/BOOT.BIN"
    manifest = {
        "application": app_name,
        "build_id": build_id,
        "xsa": str(xsa),
        "xsa_sha256": xsa_hash,
        "source": str(source),
        "source_sha256": source_hash,
        "bsp_sha256": digest(cpu / "lib/libxil.a"),
        "bsp_library": str((cpu / "lib/libxil.a").resolve()),
        "bsp_interface_files": {str(path.resolve()): digest(path) for path in interface_files},
        "bsp_compile_flags": [*CPU_FLAGS, "-O2", "-g", "-Wall", "-Wextra",
                              "-fno-tree-loop-distribute-patterns"],
        "compile_flags": [str(flag) for flag in flags],
        "link_command": [str(item) for item in link_command],
        "fsbl_sha256": digest(workspace / "fsbl/build/fsbl.elf"),
        "bit_sha256": digest(app / "_ide/bitstream/m01.bit"),
        "ps7_init_sha256": digest(app / "_ide/psinit/ps7_init.tcl"),
        "elf_sha256": digest(elf),
        "boot_bin": str(boot),
        "boot_bin_sha256": digest(boot),
        "boot_mode_sd0_expected": "0x05 (SLCR BOOT_MODE[3:0], UG585)",
        "scratch": {"address": scratch_address, "bytes": scratch_size,
                    "bss_start": bss_start, "bss_end": bss_end,
                    "heap_start": heap_start, "heap_end": heap_end,
                    "stack_start": stack_end, "stack_top": stack_top,
                    "image_end": image_end},
        "source_inputs": source_hashes,
        "source_snapshot": str(source_manifest_path),
        "implementation_evidence": {
            "summary": str(implemented_summary), "summary_sha256": digest(implemented_summary),
            "io_report": str(implemented_io), "io_report_sha256": digest(implemented_io),
            "clock_report": str(implemented_clocks), "clock_report_sha256": digest(implemented_clocks),
            "led_package_pin": "H15", "led_iostandard": "LVCMOS33",
            "heartbeat_clock_period_ns": 10.0,
        },
        "network_init": False,
        "usb_init": False,
        "development_key_or_seed_required": False,
        "sd_boot_artifacts_built": True,
        "board_validated": False,
    }
    if "H15" not in (ROOT / "board/xdc/m01.xdc").read_text(encoding="utf-8") or \
            "HALF_PERIOD_CYCLES = 50_000_000" not in (ROOT / "board/src/rtl/common/heartbeat.sv").read_text(encoding="utf-8") or \
            "CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}" not in (ROOT / "board/prj/build_m01.tcl").read_text(encoding="utf-8"):
        raise RuntimeError("G0 LED pin/heartbeat/100 MHz source assumptions changed")
    manifest["artifacts"] = {str(path.relative_to(workspace)).replace("\\", "/"): digest(path)
                              for path in (elf, build / f"{app_name}.map",
                                          build / "compile_command.json", build / "compile.log",
                                          build / "symbols.log",
                                          build / "link_command.json", build / "link.log",
                                          workspace / "fsbl/build/fsbl.elf",
                                          workspace / "fsbl/build/fsbl.map", boot,
                                          app / "_ide/bitstream/m01.bit",
                                          app / "_ide/psinit/ps7_init.tcl")}
    for relative, expected_hash in manifest["source_inputs"].items():
        if digest(ROOT / relative) != expected_hash:
            raise RuntimeError("G0 source changed during build: " + relative)
    (workspace / "g0_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                                 encoding="utf-8")
    print(f"G0_SOFTWARE_BUILD_OK build_id={build_id} boot_bin={boot}")
    print("G0_SD_BOOT_NOT_TESTED: no SD card or board was accessed")


if __name__ == "__main__":
    main()
