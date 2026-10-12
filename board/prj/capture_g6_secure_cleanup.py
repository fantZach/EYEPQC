"""Capture a build-pinned, read-only AP0 cleanup zeroization snapshot."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
TCL = ROOT / "board/prj" / "read_g6_secure_cleanup.tcl"
RANGES = {
    "diag": ("g6_secure_cleanup_diag", 120, 64),
    "frame": ("g3_frame", 65600, 64),
    "sealed": ("g3_sealed", 68096, 64),
    "tx": ("tx", 1472, 64),
    "session": ("session", 192, 4),
    "hello": ("hello", 48, 4),
    "ack": ("ack", 48, 4),
}
DEV_RANGES = {
    "private_key": ("private_key", 1632, 4),
    "random_seed": ("random_seed", 32, 4),
    "g6_sk_load": ("g6_sk_load", 1632, 64),
    "g6_seed_load": ("g6_seed_load", 32, 64),
    "random_counter": ("random_counter", 8, 4),
    "g6_ready": ("g6_ready", 4, 4),
}
READBACK_RANGES = {
    "frame": 65600,
    "sealed": 68096,
    "tx": 1472,
    "session_keys": 80,
    "session_counters": 40,
    "hello": 48,
    "ack": 48,
}
DEV_READBACK_RANGES = {
    "private_key": 1632,
    "random_seed": 32,
    "g6_sk_load": 1632,
    "g6_seed_load": 32,
    "random_counter": 8,
    "g6_ready": 4,
}
RESULT_FIELDS = {
    "frame_zero", "sealed_zero", "tx_zero", "session_keys_zero",
    "session_counters_zero", "hello_zero", "ack_zero", "total_bytes",
    "stage_before", "stage_after", "scope", "pl_gcm_full_readback",
}
DEV_RESULT_FIELDS = {
    "private_key_zero", "random_seed_zero", "g6_sk_load_zero",
    "g6_seed_load_zero", "random_counter_zero", "g6_ready_zero",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _address(value: object) -> int:
    if isinstance(value, str):
        return int(value, 0)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ValueError("Manifest DDR address is not an integer")


def load_build_identity(workspace: Path) -> tuple[dict, dict[str, dict[str, int]]]:
    manifest_path = workspace / "g6_usb_manifest.json"
    elf_path = workspace / "g6_usb" / "build" / "g6_usb.elf"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    elf_hash = digest(elf_path)
    if manifest.get("artifacts", {}).get("g6_usb/build/g6_usb.elf") != elf_hash:
        raise ValueError("G6 ELF does not match its manifest")
    profile = manifest.get("security_profile")
    if profile not in ("external_provider_unvalidated",
                       "development_jtag_mailbox_secure_cleanup"):
        raise ValueError("Cleanup readback requires an explicit G6 secure-cleanup profile")
    dev_cleanup = profile == "development_jtag_mailbox_secure_cleanup"
    xsa_hash = manifest.get("xsa_sha256")
    if not isinstance(xsa_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", xsa_hash):
        raise ValueError("Build manifest has no XSA identity")

    owned = manifest.get("owned", {})
    ranges: dict[str, dict[str, int]] = {}
    required_ranges = dict(RANGES)
    if dev_cleanup:
        required_ranges.update(DEV_RANGES)
    for label, (symbol, size, alignment) in required_ranges.items():
        entry = owned.get(symbol)
        if not isinstance(entry, dict) or int(entry.get("size", -1)) != size:
            raise ValueError("Build manifest has an invalid owned range: " + symbol)
        address = _address(entry.get("address"))
        if (address < 0x00100000 or address % alignment or
                address + size > 0x40000000):
            raise ValueError("Build manifest has an invalid DDR range: " + symbol)
        ranges[label] = {"address": address, "size": size}

    ordered = sorted((item["address"], item["address"] + item["size"], label)
                     for label, item in ranges.items())
    for previous, current in zip(ordered, ordered[1:]):
        if current[0] < previous[1]:
            raise ValueError("Manifest cleanup ranges overlap: " +
                             previous[2] + " / " + current[2])

    identity = {
        "manifest_sha256": digest(manifest_path),
        "elf_sha256": elf_hash,
        "xsa_sha256": xsa_hash,
        "security_profile": profile,
    }
    return identity, ranges


def parse_readback(stdout: str, ranges: dict[str, dict[str, int]]) -> dict:
    dev_names = set(DEV_READBACK_RANGES)
    has_dev_ranges = bool(dev_names.intersection(ranges))
    if has_dev_ranges and not dev_names.issubset(ranges):
        raise ValueError("Development key readback ranges are incomplete")
    readback_ranges = dict(READBACK_RANGES)
    result_fields = set(RESULT_FIELDS)
    if has_dev_ranges:
        readback_ranges.update(DEV_READBACK_RANGES)
        result_fields.update(DEV_RESULT_FIELDS)
    summaries = re.findall(r"^G6_CLEANUP_READBACK (.+)$", stdout, re.MULTILINE)
    pass_markers = re.findall(r"^G6_CLEANUP_READBACK_PASS\s*$", stdout, re.MULTILINE)
    if (len(summaries) != 1 or len(pass_markers) != 1 or
            re.search(r"^G6_CLEANUP_READBACK_FAIL\b", stdout, re.MULTILINE)):
        raise ValueError("XSDB output has no successful G6 cleanup readback")
    fields: dict[str, str] = {}
    for token in summaries[0].split():
        if "=" not in token:
            raise ValueError("Malformed G6 cleanup readback field")
        name, value = token.split("=", 1)
        if name in fields:
            raise ValueError("Duplicate G6 cleanup readback field: " + name)
        fields[name] = value
    if set(fields) != result_fields:
        raise ValueError("G6 cleanup readback fields do not match the expected schema")

    parsed: dict[str, object] = {}
    boolean_fields = {
        "frame_zero", "sealed_zero", "tx_zero", "session_keys_zero",
        "session_counters_zero", "hello_zero", "ack_zero",
    }
    if has_dev_ranges:
        boolean_fields.update(DEV_RESULT_FIELDS)
    for name in boolean_fields:
        try:
            value = int(fields[name], 10)
        except ValueError as exc:
            raise ValueError("Invalid cleanup boolean: " + name) from exc
        if value not in (0, 1):
            raise ValueError("Cleanup boolean is outside range: " + name)
        parsed[name] = value
        if value != 1:
            raise ValueError("Cleanup readback reported nonzero DDR data: " + name)
    for name in ("total_bytes", "stage_before", "stage_after"):
        try:
            value = int(fields[name], 10)
        except ValueError as exc:
            raise ValueError("Invalid cleanup integer: " + name) from exc
        if not 0 <= value <= 0xFFFFFFFF:
            raise ValueError("Cleanup integer is outside uint32: " + name)
        parsed[name] = value
    if parsed["stage_before"] != 6 or parsed["stage_after"] != 6:
        raise ValueError("Cleanup diagnostic did not remain in COMPLETE state")
    expected_total = sum(readback_ranges.values())
    if parsed["total_bytes"] != expected_total:
        raise ValueError("Cleanup readback byte count does not match the ABI")
    if fields["scope"] != "PS_AP0_DDR_only" or \
            fields["pl_gcm_full_readback"] != "not_proven":
        raise ValueError("Cleanup readback scope is invalid or overstated")
    parsed["scope"] = fields["scope"]
    parsed["pl_gcm_full_readback"] = fields["pl_gcm_full_readback"]

    observed: dict[str, dict[str, int]] = {}
    for line in re.finditer(r"^G6_CLEANUP_RANGE (.+)$", stdout, re.MULTILINE):
        item: dict[str, str] = {}
        for token in line.group(1).split():
            if "=" not in token:
                raise ValueError("Malformed G6 cleanup range record")
            name, value = token.split("=", 1)
            if name in item:
                raise ValueError("Duplicate G6 cleanup range field: " + name)
            item[name] = value
        if set(item) != {"name", "bytes", "words", "zero"}:
            raise ValueError("G6 cleanup range record has an unexpected schema")
        name = item["name"]
        if name not in readback_ranges or name in observed:
            raise ValueError("Unexpected or duplicate G6 cleanup range: " + name)
        try:
            byte_count, words, zero = (int(item[key], 10)
                                       for key in ("bytes", "words", "zero"))
        except ValueError as exc:
            raise ValueError("Invalid G6 cleanup range value") from exc
        if (byte_count != readback_ranges[name] or words != byte_count // 4 or
                zero != 1):
            raise ValueError("G6 cleanup range is incomplete or nonzero: " + name)
        observed[name] = {"bytes": byte_count, "words": words, "zero": zero}
    if set(observed) != set(readback_ranges):
        raise ValueError("G6 cleanup readback omitted one or more DDR ranges")
    parsed["ranges"] = observed
    return parsed


def capture(workspace: Path, tool_root: Path, output_prefix: Path) -> dict:
    identity, ranges = load_build_identity(workspace)
    xsdb = tool_root / "Vivado" / "bin" / "xsdb.bat"
    if not xsdb.is_file() or not TCL.is_file():
        raise FileNotFoundError("XSDB or the G6 cleanup readback Tcl script is missing")
    args = []
    for label in ("diag", "frame", "sealed", "tx", "session", "hello", "ack"):
        item = ranges[label]
        args.extend((hex(item["address"]), str(item["size"])))
    if "private_key" in ranges:
        for label in DEV_RANGES:
            item = ranges[label]
            args.extend((hex(item["address"]), str(item["size"])))

    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = output_prefix.with_suffix(".stdout.log")
    stderr_path = output_prefix.with_suffix(".stderr.log")
    command = [str(xsdb), str(TCL), *args]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                timeout=60, check=False)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        raise TimeoutError("G6 cleanup readback exceeded 60 seconds") from exc
    stdout_path.write_text(result.stdout, encoding="utf-8")
    stderr_path.write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError("XSDB cleanup readback failed with exit " +
                           str(result.returncode))
    parsed = parse_readback(result.stdout, ranges)
    evidence_scope = (
        "read-only PS AP0 DDR zero-or checks; no keys, packet payloads, "
        "or full PL GCM state emitted"
    )
    if identity["security_profile"] == "development_jtag_mailbox_secure_cleanup":
        evidence_scope = (
            "read-only PS AP0 DDR zero-or checks after terminal development FAULT; "
            "test-key and provisioning ranges emit zero flags only; no payload "
            "or full PL GCM state emitted"
        )
    record = {
        "schema": "eyepqc-g6-secure-cleanup-readback-v1",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "build": identity,
        "ranges": ranges,
        "readback": parsed,
        "evidence_scope": evidence_scope,
    }
    output_prefix.with_suffix(".json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--tool-root", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = capture(args.workspace.resolve(), args.tool_root.resolve(),
                         args.output_prefix.resolve())
    except (FileNotFoundError, OSError, RuntimeError, TimeoutError, ValueError) as exc:
        print("G6_CLEANUP_READBACK_CAPTURE_FAIL", str(exc))
        return 1
    print("G6_CLEANUP_READBACK_CAPTURE_OK")
    print("ELF_SHA256", record["build"]["elf_sha256"])
    print("RANGES_ZERO", len(record["readback"]["ranges"]))
    print("EVIDENCE_SCOPE", record["evidence_scope"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
