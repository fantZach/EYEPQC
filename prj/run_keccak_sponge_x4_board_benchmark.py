"""Verify a KX41 firmware build and capture one temporary JTAG/UART run."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import time
from pathlib import Path

import serial

try:
    from .parse_keccak_sponge_x4_board_benchmark import parse_log
except ImportError:  # Allow direct execution by the board runner.
    from parse_keccak_sponge_x4_board_benchmark import parse_log

ROOT = Path(__file__).resolve().parents[1]
XSDB = Path(r"E:\fpg\2026.1\Vivado\bin\xsdb.bat")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def audit_build(work: Path) -> dict:
    manifest_path = work / "build_manifest.json"
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    timing = m["xsa_timing_gate"]
    require(timing["fully_routed"] and timing["wns"] >= 0 and timing["whs"] >= 0 and
            timing["max_failing_endpoints"] == 0 and timing["min_failing_endpoints"] == 0,
            "KX41 XSA is not timing eligible")
    require(m["address_map"] == {"module": "keccak_sponge_x4_axi_lite", "base": "0x43C10000",
            "range": "4 KiB", "id": "0x4B583431", "version": "0x00010000"},
            "firmware manifest is not KX41 ID 4b583431/version 00010000")
    require(digest(ROOT / m["xsa_repo_relative"]) == m["xsa_sha256"], "matched XSA changed")
    require(digest(ROOT / m["xsa_manifest_repo_relative"]) == m["xsa_manifest_sha256"],
            "matched XSA manifest changed")
    checks = 0
    for rel, expected in m["project_source_sha256"].items():
        require(digest(ROOT / rel) == expected, "firmware project source changed: " + rel)
        checks += 1
    vendor = work / "vendor/mlkem"
    for rel, expected in m["vendored_mlkem_inputs_sha256"].items():
        path = (vendor / rel).resolve()
        require(path.is_relative_to(vendor.resolve()), "vendor manifest path traversal")
        require(digest(path) == expected, "vendored ML-KEM source changed: " + rel)
        checks += 1
    for rel, expected in m["bsp_generated_inputs_sha256"].items():
        path = (work / rel).resolve()
        require(path.is_relative_to(work.resolve()), "BSP manifest path traversal")
        require(digest(path) == expected, "generated BSP input changed: " + rel)
        checks += 1
    for rel, expected in m["generated_inputs_sha256"].items():
        path = work / "firmware/include" / rel
        require(digest(path) == expected, "generated KAT/config input changed: " + rel)
        checks += 1
    elf = work / m["firmware"]["elf"]["path"]
    bsp = work / "bsp"
    require(digest(elf) == m["firmware"]["elf"]["sha256"], "firmware ELF changed")
    require(digest(work / "matching_system.bit") == m["matching_artifacts"]["bitstream_sha256"],
            "matched bitstream changed")
    require(digest(work / "matching_ps7_init.tcl") == m["matching_artifacts"]["ps7_init_sha256"],
            "matched PS7 initialization changed")
    require(digest(bsp / "ps7_cortexa9_0/lib/libxil.a") == m["bsp_archive_sha256"],
            "generated BSP archive changed")
    checks += 5
    return {"manifest_sha256": digest(manifest_path), "input_hash_checks": checks,
            "elf_sha256": m["firmware"]["elf"]["sha256"], "xsa_sha256": m["xsa_sha256"],
            "counter_hz_expected": m["cpu_clock_hz_from_new_xsa_bsp"] // 2,
            "timing": timing}


def capture_uart(ser, proc, timeout: float, *, started_at: float | None = None,
                 clock=time.monotonic) -> tuple[bytes, int | None, float]:
    """Keep collecting after a successful XSDB loader exit until firmware completion."""
    start = clock() if started_at is None else started_at
    raw = bytearray()
    try:
        while clock() - start < timeout:
            chunk = ser.read(4096)
            if chunk:
                raw.extend(chunk)
            code = proc.poll()
            if b"KECCAK_SX4_BENCH_DONE" in raw and code is not None:
                break
            if code is not None and code != 0:
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    return bytes(raw), proc.returncode, clock() - start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--firmware", type=Path, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--serial-port")
    ap.add_argument("--serial-timeout", type=float, default=180.0)
    ap.add_argument("--xsdb", type=Path, default=XSDB)
    ap.add_argument("--verify-only", action="store_true",
                    help="verify build hashes and timing eligibility without opening UART/JTAG")
    args = ap.parse_args()
    require(args.label and Path(args.label).name == args.label and args.label not in (".", ".."),
            "label must be one path component")
    work = Path(args.firmware).absolute()
    audit = audit_build(work)
    if args.verify_only:
        print(json.dumps({"status": "firmware_manifest_verified_no_hardware_access", **audit}, indent=2))
        return 0
    require(args.serial_port is not None, "--serial-port is required for a hardware capture")
    xsdb = args.xsdb.resolve()
    require(xsdb.is_file(), "XSDB executable missing: " + str(xsdb))
    evidence = ROOT / "build/keccak_sponge_x4_board" / args.label
    evidence.mkdir(parents=True, exist_ok=False)
    raw = bytearray()
    start = time.monotonic()
    code = None
    with serial.Serial(port=None, baudrate=115200, timeout=0.1) as ser:
        ser.dtr = False
        ser.rts = False
        ser.port = args.serial_port
        ser.open()
        ser.reset_input_buffer()
        with (evidence / "jtag_stdout.log").open("wb") as out, \
                (evidence / "jtag_stderr.log").open("wb") as err:
            proc = subprocess.Popen([str(xsdb), str(ROOT / "prj/run_keccak_sponge_x4_jtag.tcl"),
                                     str(work)], stdout=out, stderr=err)
            captured, code, elapsed = capture_uart(ser, proc, args.serial_timeout, started_at=start)
            raw.extend(captured)
    (evidence / "uart.log").write_bytes(raw)
    text = raw.decode("utf-8", errors="replace").replace("\r", "")
    record = {"status": "captured", "label": args.label, "firmware_audit": audit,
              "jtag_returncode": code, "elapsed_wall_seconds": elapsed,
              "captured_utc": datetime.now(timezone.utc).isoformat(),
              "uart_sha256": hashlib.sha256(raw).hexdigest(), "uart_bytes": len(raw),
              "persistent_storage_written": False, "board_claim": "not asserted until parser passes"}
    if code == 0 and "KECCAK_SX4_BENCH_DONE" in text:
        try:
            record["parsed"] = parse_log(text, expected_counter_hz=audit["counter_hz_expected"])
            record["status"] = "passed"
        except ValueError as exc:
            record["status"] = "failed_audit"
            record["audit_error"] = str(exc)
    else:
        record["status"] = "incomplete"
    result = evidence / "capture_result.json"
    result.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))
    return 0 if record["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
