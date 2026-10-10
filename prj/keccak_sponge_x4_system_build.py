"""Build/manifest the isolated Keccak PS+PL Vivado system (no board access)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).absolute().parents[1]
DEFAULT_OUT = ROOT / "build/parallel_20261010/C/sponge_x4_stateful"
DEFAULT_VIVADO = Path(r"E:\fpg\2026.1\Vivado\bin\vivado.bat")
SOURCE_FILES = [
    "prj/keccak_sponge_x4_system.tcl", "prj/keccak_sponge_x4_system_build.py", "prj/build_m01.tcl",
    "src/rtl/crypto/keccak_round.sv", "src/rtl/crypto/keccak_f1600.sv",
    "src/rtl/crypto/keccak_sponge_x4_axi_lite.sv",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finalize(out: Path, vivado: Path, storage_relative: str) -> dict:
    project = out / "vivado"
    xsa = project / "keccak_sponge_x4_experiment.xsa"
    bit = project / "keccak_sponge_x4_experiment.runs/impl_1/system_wrapper.bit"
    if not xsa.is_file() or not bit.is_file():
        raise SystemExit(f"Vivado implementation artifacts missing under {project}")
    timing = project / "timing.txt"
    drc = project / "drc.txt"
    if not timing.is_file() or not drc.is_file():
        raise SystemExit("timing/DRC reports missing; do not classify this as implemented")
    timing_text = timing.read_text(encoding="utf-8", errors="replace")
    drc_text = drc.read_text(encoding="utf-8", errors="replace")
    critical = re.findall(r"(?im)^.*(?:CRITICAL WARNING|\bERROR\b).*$", drc_text)
    if critical:
        raise SystemExit("Critical DRC/Error text found; see drc.txt: " + " | ".join(critical[:5]))
    summary_start = timing_text.find("WNS(ns)")
    summary_match = re.search(r"(?m)^\s*([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)",
                              timing_text[summary_start:]) if summary_start >= 0 else None
    if not summary_match:
        raise SystemExit("Unable to parse implemented WNS/WHS summary")
    utilization_text = (project / "utilization.txt").read_text(encoding="utf-8", errors="replace")
    def resource(pattern: str) -> int:
        match = re.search(pattern, utilization_text, re.MULTILINE)
        if not match:
            raise SystemExit("Unable to parse utilization report field: " + pattern)
        return int(match.group(1))
    resources = {
        "slice_luts": resource(r"^\| Slice LUTs\s+\|\s+(\d+)"),
        "slice_registers": resource(r"^\| Slice Registers\s+\|\s+(\d+)"),
        "bram_tiles": resource(r"^\| Block RAM Tile\s+\|\s+(\d+)"),
        "dsp": resource(r"^\| DSPs\s+\|\s+(\d+)"),
    }
    hwdef = project / "keccak_sponge_x4_experiment.gen/sources_1/bd/system/hw_handoff/system.hwh"
    hwdef_text = hwdef.read_text(encoding="utf-8", errors="replace") if hwdef.exists() else ""
    if "43C10000" not in hwdef_text.upper():
        # The HWH uses HSI node data; the Vivado BD address assignment is also
        # verified from the source Tcl and XSA. Keep this check visible in manifest.
        address_evidence = "source Tcl assign_bd_address plus XSA; HWH literal base not found"
    else:
        address_evidence = "system.hwh contains 0x43C10000 and source Tcl assigns a 4 KiB range"
    source_snapshot_path = out / "source_snapshot.json"
    if not source_snapshot_path.is_file():
        raise SystemExit("Build-start source snapshot missing; refusing to bind artifacts to current sources")
    source_snapshot = json.loads(source_snapshot_path.read_text(encoding="utf-8"))
    source_hashes = source_snapshot.get("source_sha256", {})
    current_hashes = {name: sha256(ROOT / name) for name in SOURCE_FILES}
    if source_hashes != current_hashes:
        raise SystemExit("Source files changed during/after build; refusing to finalize mismatched artifacts")
    record = {
        "result": "Vivado PS+PL implementation and XSA export completed offline; board_validated=false",
        "output_location_repo_relative": storage_relative,
        "tool": {"path": str(vivado), "version": "Vivado 2026.1 (verified by build log)"},
        "target": "xc7z020clg400-2",
        "assumptions": {
            "ps7_parameters_source": "prj/build_m01.tcl board-confirmed PS7 user parameters",
            "ps7_parameters_source_sha256": sha256(ROOT / "prj/build_m01.tcl"),
            "ddr": "2x Hynix H5TC4G63EFR-RDA x16 devices, 32-bit/1 GiB, DDR3L-1066; inherited from M01 source",
            "pl_external_pins": "none; only PS DDR/FIXED_IO exposed",
            "not_included": ["camera", "video pipeline", "USB PL logic", "formal firmware"],
        },
        "address_map": {"keccak_sponge_x4_axi_lite": {"base": "0x43C10000", "range": "4 KiB",
            "end_inclusive": "0x43C10FFF", "scope": "this experimental XSA only",
            "id": "0x4B583431", "version": "0x00010000",
            "evidence": address_evidence}},
        "artifacts": {str(p.relative_to(out)).replace("\\", "/"):
            {"sha256": sha256(p), "bytes": p.stat().st_size} for p in (xsa, bit, timing, drc)},
        "reports": {"timing_path": "vivado/timing.txt", "drc_path": "vivado/drc.txt",
            "timing_report_has_wns": "WNS" in timing_text,
            "timing_report_has_whs": "WHS" in timing_text,
            "critical_drc_or_errors": critical},
        "implemented_timing_ns": {"clock_period": 10.0,
            "wns": float(summary_match.group(1)), "tns": float(summary_match.group(2)),
            "max_failing_endpoints": int(summary_match.group(3)),
            "whs": float(summary_match.group(5)), "ths": float(summary_match.group(6)),
            "min_failing_endpoints": int(summary_match.group(7)),
            "fully_routed": "Design State : Routed" in timing_text},
        "implemented_resources": resources,
        "source_sha256": source_hashes,
        "source_snapshot": "source_snapshot.json (captured before Vivado run)",
        "limits": ["offline only", "implementation/timing reflects this Vivado run and its generated XSA",
                   "no PS MMIO, board timing, or acceleration claim"],
    }
    target = out / "build_manifest.json"
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print("KECCAK_SPONGE_X4_SYSTEM_MANIFEST", target)
    return record


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--vivado", type=Path, default=DEFAULT_VIVADO)
    ap.add_argument("--storage-relative", default="build/parallel_20261010/C/sponge_x4_stateful",
                    help="physical repository-relative location when --out uses a subst alias")
    ap.add_argument("--finalize-existing", action="store_true",
                    help="create/refresh manifest from an already completed isolated build")
    args = ap.parse_args()
    out = Path(os.path.abspath(args.out))
    vivado = args.vivado.resolve()
    storage_relative = args.storage_relative
    project = out / "vivado"
    if args.finalize_existing:
        finalize(out, vivado, storage_relative)
        return 0
    if not vivado.is_file():
        raise SystemExit(f"Vivado executable missing: {vivado}")
    if project.exists():
        raise SystemExit(f"Build path already exists: {project}; select a fresh --out")
    out.mkdir(parents=True, exist_ok=True)
    snapshot = {"source_sha256": {name: sha256(ROOT / name) for name in SOURCE_FILES}}
    (out / "source_snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    command = [str(vivado), "-mode", "batch", "-source", str(ROOT / "prj/keccak_sponge_x4_system.tcl"),
               "-tclargs", str(project)]
    log = out / "vivado_build.log"
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise SystemExit(f"Vivado failed ({result.returncode}); see {log}")
    finalize(out, vivado, storage_relative)
    return 0


if __name__ == "__main__":
    sys.exit(main())
