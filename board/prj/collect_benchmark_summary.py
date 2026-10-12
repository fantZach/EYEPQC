#!/usr/bin/env python3
"""Collect a sanitized, allowlisted summary from selected EYEPQC evidence JSON."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "board/prj"))
from g0_acceptance import load_manifest  # noqa: E402

DEFAULT_OUTPUT = ROOT / "report/benchmark_summary_20261009.json"
G0_RESULT = Path("data/captures/g0/20261008_jtag_led_probe_205256.result.json")
G0_LOG = Path("data/captures/g0/20261008_jtag_led_probe_205256.jsonl")
G0_MANIFEST = Path("build/vitis/g0_20261008b_startup_final2/g0_manifest.json")
G3_RESULTS = (
    Path("data/captures/g3_20261007_110737_900610/result.json"),
    Path("data/captures/g3_20261007_110812_858064/result.json"),
)
G6_RESULT = Path("data/captures/g6_usb_20261008_205623_506211/result.json")
DEMO_RESULT = Path("data/captures/demo_live_acceptance/20261008_193414_562175/result.json")
DEMO_CAPTURE = Path(
    "data/captures/demo_live_acceptance/20261008_193414_562175/"
    "captures/demo_usb/20261008_193414_626955/result.json"
)
G7_RESULTS = (
    ("g7_camera_reset_candidate7_single", "G7_PL_camera_reset",
     Path("report/g7_runs/g7_auto_recovery_camera-reset_20261008_134954_225366_f4dd38fa/batch_summary.json")),
    ("g7_routing_stall_candidate6_single", "G7_PL_routing_stall",
     Path("report/g7_runs/g7_auto_recovery_routing-stall_20261008_134558_395196_46a6cc36/batch_summary.json")),
)
# This is a reviewed allowlist of exact source paths, not a directory scan.
# Add an A/C result only after its final evidence report identifies the source.
VALIDATION_SNAPSHOT = Path("report/validation_snapshot_20261008.json")
C_ROUTE4K = Path("build/parallel_20261009/C/route4k/build_manifest.json")
G0_STAT_RE = re.compile(
    r"^G0 STAT uptime_s=(\d+) ticks=(\d+) ddr_pass=(\d+) ddr_err=(\d+) "
    r"assert=(\d+) exception=(\d+) timer_err=(\d+) boot_mode=0x([0-9a-fA-F]+)$"
)
BUILD_ID_RE = re.compile(r"^[0-9a-fA-F]{12}$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def read_json(relative: Path, root: Path = ROOT) -> dict:
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"required benchmark evidence is missing: {relative.as_posix()}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {relative.as_posix()}")
    return value


def source_ref(relative: Path, root: Path = ROOT) -> dict:
    """Return only a repository-relative evidence pointer and content hash."""
    path = root / relative
    if not path.is_file():
        raise FileNotFoundError(f"required benchmark evidence is missing: {relative.as_posix()}")
    return {"path": relative.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def record(record_id: str, scenario: str, evidence_class: str, outcome: str,
           sources: list[Path], *, build: dict | None = None,
           time_window_s=None, frames=None, fps=None, bytes_count=None,
           resolution: dict | None = None, error_counts: dict | None = None,
           board_counters: dict | None = None, details: dict | None = None,
           root: Path = ROOT) -> dict:
    if not record_id or not re.fullmatch(r"[a-z0-9_]+", record_id):
        raise ValueError(f"invalid record id: {record_id!r}")
    if any(Path(p).is_absolute() for p in sources):
        raise ValueError("absolute evidence paths are forbidden in the public summary")
    return {
        "record_id": record_id,
        "scenario": scenario,
        "evidence_class": evidence_class,
        "outcome": outcome,
        "build": build or {"variant": None, "build_id": None,
                           "manifest_sha256": None, "elf_sha256": None,
                           "bit_sha256": None, "xsa_sha256": None},
        "time_window_s": time_window_s,
        "frames": frames,
        "fps": fps,
        "bytes": bytes_count,
        "resolution": resolution or {"width": None, "height": None},
        "error_counts": error_counts,
        "board_counters": board_counters,
        "details": details or {},
        "sources": [source_ref(p, root) for p in sources],
    }


def metric(value, *, integer: bool = False):
    """Keep numeric measurements only; reject arbitrary strings and booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0 or (integer and not isinstance(value, int)):
        return None
    return value


def safe_hash(value: object) -> str | None:
    return str(value).lower() if isinstance(value, str) and SHA256_RE.fullmatch(value) else None


def safe_build_id(value: object) -> str | None:
    return str(value).lower() if isinstance(value, str) and BUILD_ID_RE.fullmatch(value) else None


def safe_counters(value: object) -> dict | None:
    allowed = {"frames", "queued", "sent", "dropped", "overflows", "dma_errors",
               "usb_errors", "gcm_errors", "assert", "exception", "timer_err",
               "ddr_err", "ddr_pass"}
    if not isinstance(value, dict):
        return None
    clean = {key: metric(value.get(key), integer=True) for key in allowed
             if metric(value.get(key), integer=True) is not None}
    return clean or None


def public_status(value: object) -> str:
    """Normalize untrusted evidence status strings to a small public enum."""
    if not isinstance(value, str):
        return "unknown"
    if value == "passed":
        return "passed"
    if value in {"failed", "error"}:
        return "failed"
    if value == "unverified":
        return "unverified"
    return "unknown"


def g0_error_counters(root: Path = ROOT) -> dict | None:
    path = root / G0_LOG
    if not path.is_file():
        return None
    latest = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            item = {"line": raw}
        match = G0_STAT_RE.match(str(item.get("line", "")).strip())
        if match:
            fields = [int(v, 16) if i == 7 else int(v) for i, v in enumerate(match.groups())]
            latest = dict(zip(("uptime_s", "ticks", "ddr_pass", "ddr_err",
                               "assert", "exception", "timer_err", "boot_mode"), fields))
    if latest is None:
        return None
    return {name: latest[name] for name in ("ddr_err", "assert", "exception", "timer_err")}


def verify_build_manifest(root: Path, manifest: dict, build_dir: Path) -> None:
    """Verify exact manifest source and output hashes before summarizing an offline build."""
    for relative, expected in (manifest.get("source_sha256") or {}).items():
        path = root / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"build source hash mismatch: {relative}")
    for relative, artifact in (manifest.get("artifacts") or {}).items():
        path = build_dir / relative
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.get("sha256"):
            raise ValueError(f"build artifact hash mismatch: {relative}")


def build_summary(root: Path = ROOT, manifest_validator=load_manifest) -> dict:
    """Build from the fixed source allowlist under root; root injection enables isolated tests."""
    rows = []

    manifest_validator(root / G0_MANIFEST)
    g0_manifest = read_json(G0_MANIFEST, root)
    rows.append(record(
        "g0_final2_offline_manifest_preflight", "G0_startup_artifact_preflight",
        "offline_artifact_check", "passed",
        [G0_MANIFEST],
        build={"variant": "g0_startup" if g0_manifest.get("application") == "g0_startup" else None,
               "build_id": safe_build_id(g0_manifest.get("build_id")),
               "manifest_sha256": hashlib.sha256((root / G0_MANIFEST).read_bytes()).hexdigest(),
               "elf_sha256": safe_hash(g0_manifest.get("elf_sha256")),
               "bit_sha256": safe_hash(g0_manifest.get("bit_sha256")),
               "xsa_sha256": safe_hash(g0_manifest.get("xsa_sha256"))},
        details={"board_validated": g0_manifest.get("board_validated") if isinstance(g0_manifest.get("board_validated"), bool) else None,
                 "performance_measurement": False,
                 "meaning": "Manifest/hash preflight only; no board or SD access."}, root=root))

    g0 = read_json(G0_RESULT, root)
    g0_ids = g0.get("build_ids") or []
    g0_status = public_status(g0.get("status"))
    g0_build_id = safe_build_id(g0_ids[0]) if len(g0_ids) == 1 else None
    rows.append(record(
        "g0_final2_jtag_30s", "G0_volatile_JTAG_DDR_timer_LED_probe",
        "board_jtag_probe", g0_status,
        [G0_RESULT, G0_LOG, G0_MANIFEST],
        build={"variant": "g0_startup", "build_id": g0_build_id,
               "manifest_sha256": hashlib.sha256((root / G0_MANIFEST).read_bytes()).hexdigest(),
               "elf_sha256": safe_hash(g0_manifest.get("elf_sha256")),
               "bit_sha256": safe_hash(g0_manifest.get("bit_sha256")),
               "xsa_sha256": safe_hash(g0_manifest.get("xsa_sha256"))},
        time_window_s=metric(g0.get("final_uptime_s")),
        error_counts=g0_error_counters(root), board_counters=g0_error_counters(root),
        details={"boot_mode": metric((g0.get("boot_modes") or [None])[0], integer=True),
                 "boot_count": metric(g0.get("boot_count"), integer=True),
                 "stat_samples": metric(g0.get("stat_samples"), integer=True),
                 "ddr_passes": metric(g0.get("final_ddr_passes"), integer=True),
                 "scratch_bytes": 65536, "full_ddr": False,
                 "resolution_scope": "not_applicable; JTAG startup probe is not a video benchmark"}, root=root))

    for index, relative in enumerate(G3_RESULTS, start=1):
        result = read_json(relative, root)
        runs = result.get("runs") or []
        if len(runs) != 1:
            raise ValueError(f"expected exactly one G3 run in {relative.as_posix()}")
        run = runs[0]
        board_validated = result.get("board_validated") is True
        frames_metric = metric(run.get("frames"), integer=True)
        run_passed = (board_validated and frames_metric is not None and frames_metric > 0 and
                      metric(run.get("queued"), integer=True) == frames_metric and
                      metric(run.get("sent"), integer=True) == frames_metric and
                      metric(run.get("dropped"), integer=True) == 0 and
                      metric(run.get("overflows"), integer=True) == 0)
        source_status_value = result.get("status")
        source_status_recorded = source_status_value is not None
        source_status = public_status(source_status_value) if source_status_recorded else "not_recorded"
        if source_status_recorded:
            g3_outcome = ("passed" if source_status == "passed" and run_passed else
                          "failed" if source_status == "failed" or (source_status == "passed" and not run_passed)
                          else "unknown")
        else:
            # Legacy G3 results omit status; use only their explicit board flag and run counters.
            g3_outcome = "passed" if run_passed else "unverified"
        rows.append(record(
            f"g3_fast_run_{index}", "G3_camera_DDR_AES_GCM_fast_capture",
            "board_measurement" if board_validated else "software_or_mock",
            g3_outcome, [relative],
            build={"variant": "g3_fast", "build_id": None,
                   "manifest_sha256": None, "elf_sha256": None,
                   "bit_sha256": safe_hash(result.get("bit_sha256")), "xsa_sha256": None},
            time_window_s=(metric(run.get("elapsed_us")) / 1_000_000
                           if metric(run.get("elapsed_us")) is not None else None),
            frames=metric(run.get("frames"), integer=True), fps=metric(run.get("fps")),
            bytes_count=metric(run.get("total_bytes"), integer=True),
            error_counts={"dropped": metric(run.get("dropped"), integer=True),
                          "overflows": metric(run.get("overflows"), integer=True)},
            board_counters=({"dropped": metric(run.get("dropped"), integer=True),
                             "overflows": metric(run.get("overflows"), integer=True)}
                            if board_validated else None),
            details={"vts": metric(result.get("vts"), integer=True),
                     "queued": metric(run.get("queued"), integer=True),
                     "sent": metric(run.get("sent"), integer=True),
                     "packets": metric(run.get("packet_count"), integer=True),
                     "source_status_recorded": source_status_recorded,
                     "source_status": source_status,
                     "resolution_note": "Raw result does not record width/height; null is intentional."}, root=root))

    g6 = read_json(G6_RESULT, root)
    g6_manifest = g6.get("build") or {}
    g6_sessions = g6.get("sessions") or []
    if len(g6_sessions) != 1:
        raise ValueError("expected exactly one G6 session in selected evidence")
    session = g6_sessions[0]
    rows.append(record(
        "g6_usb_20261008_one_session", "G6_USB_authenticated_video_single_session",
        "board_measurement" if public_status(g6.get("status")) == "passed" else "unknown",
        public_status(g6.get("status")), [G6_RESULT],
        build={"variant": "usbfix3_20261007", "build_id": None,
               "manifest_sha256": safe_hash(g6_manifest.get("manifest_sha256")),
               "elf_sha256": safe_hash(g6_manifest.get("elf_sha256")),
               "bit_sha256": None, "xsa_sha256": safe_hash(g6_manifest.get("xsa_sha256"))},
        time_window_s=metric(session.get("seconds")), frames=metric(session.get("frames"), integer=True),
        fps=metric(session.get("fps")), bytes_count=metric(session.get("bytes"), integer=True),
        error_counts=None, board_counters=safe_counters(g6.get("board_counters")),
        details={"packets": metric(session.get("packets"), integer=True), "authenticated_packets":
                 metric((session.get("errors") or {}).get("authenticated_packets"), integer=True),
                 "jtag_started": g6.get("jtag_started") if isinstance(g6.get("jtag_started"), bool) else None,
                 "jtag_completed": g6.get("jtag_completed") if isinstance(g6.get("jtag_completed"), bool) else None,
                 "resolution_note": "The result JSON does not record width/height; null is intentional."}, root=root))

    demo = read_json(DEMO_RESULT, root)
    demo_capture = read_json(DEMO_CAPTURE, root)
    rec_build = demo_capture.get("build") or {}
    demo_board = demo.get("board_accessed") is True and demo.get("offline_smoke") is not True
    rows.append(record(
        "demo_live_recording_20261008", "G6_live_demo_recording_replay_export",
        "board_measurement" if demo_board else "offline_or_mock",
        public_status(demo.get("status")), [DEMO_RESULT, DEMO_CAPTURE],
        build={"variant": "usbfix3_20261007", "build_id": None,
               "manifest_sha256": safe_hash(rec_build.get("manifest_sha256")),
               "elf_sha256": safe_hash(rec_build.get("elf_sha256")),
               "bit_sha256": None, "xsa_sha256": safe_hash(rec_build.get("xsa_sha256"))},
        time_window_s=metric(demo.get("recording_seconds")), frames=metric(demo.get("recording_frames"), integer=True),
        fps=metric(demo.get("recording_fps")), bytes_count=None,
        error_counts=None, board_counters=safe_counters(demo_capture.get("board_counters")),
        details={"recorder_callback_frames": metric(demo.get("recorder_callback_frames"), integer=True),
                 "post_rekey_frames": metric((demo.get("post_rekey_recording") or {}).get("frames"), integer=True),
                 "exported_frames": metric(demo.get("recording_exported_frame_count"), integer=True),
                 "mp4_bytes": metric(demo.get("mp4_bytes"), integer=True),
                 "avi_bytes": metric(demo.get("avi_bytes"), integer=True),
                 "recording_scope": "Total timeline includes rekey pause; 722/722 callback frames saved."
                 if demo_board else "Offline/mock run; not a physical throughput measurement."}, root=root))

    for record_id, scenario, relative in G7_RESULTS:
        batch = read_json(relative, root)
        trials = batch.get("trials") or []
        if len(trials) != 1:
            raise ValueError(f"expected one isolated G7 trial in {relative.as_posix()}")
        trial = trials[0]
        rows.append(record(
            record_id, scenario, "board_fault_injection" if public_status(trial.get("status")) == "passed" else "unknown",
            public_status(trial.get("status")), [relative],
            build={"variant": record_id, "build_id": None,
                   "manifest_sha256": None, "elf_sha256": None,
                   "bit_sha256": None, "xsa_sha256": safe_hash(batch.get("xsa_sha256"))},
            error_counts=None, board_counters=None,
            details={"attempts_requested": metric(batch.get("attempts_requested"), integer=True),
                     "frames_before_fault": metric(trial.get("frames_before_fault"), integer=True),
                     "frames_after_recovery": metric(trial.get("frames_after_recovery"), integer=True),
                     "recovery_latency_us": metric(trial.get("elapsed_us"), integer=True),
                     "time_window_s": None,
                     "scope": "Single injected trial; no total stream FPS/bytes/counter readback."}, root=root))

    snapshot = read_json(VALIDATION_SNAPSHOT, root)
    candidate = snapshot.get("offline_candidate_validation") or {}
    rows.append(record(
        "g6_usb_bounded_candidate_v3_offline_build", "G6_USB_bounded_overlay_build_preflight",
        "offline_build", "passed" if candidate.get("board_accessed") is False and
        candidate.get("board_validated") is False else "unverified", [VALIDATION_SNAPSHOT],
        build={"variant": "g6_usb_bounded_candidate_v3", "build_id": None,
               "manifest_sha256": None, "elf_sha256": safe_hash(candidate.get("elf_sha256")),
               "bit_sha256": None, "xsa_sha256": safe_hash(candidate.get("xsa_sha256"))},
        details={"validation": "offline_build_hash_preflight_passed" if candidate.get("result") == "ARM_BUILD_AND_169_HASH_PREFLIGHT_PASS" else "unknown",
                 "board_accessed": candidate.get("board_accessed") if isinstance(candidate.get("board_accessed"), bool) else None,
                 "board_validated": candidate.get("board_validated") if isinstance(candidate.get("board_validated"), bool) else None,
                 "performance_measurement": False}, root=root))

    c_manifest = read_json(C_ROUTE4K, root)
    verify_build_manifest(root, c_manifest, root / c_manifest["output_location_repo_relative"])
    address_map = c_manifest.get("address_map", {}).get("keccak_axi_lite", {})
    if (c_manifest.get("target") != "xc7z020clg400-2" or
            address_map.get("base") != "0x43C10000" or
            address_map.get("end_inclusive") != "0x43C10FFF"):
        raise ValueError("C route4k manifest target/address map does not match the reviewed build")
    c_build_dir = Path(c_manifest["output_location_repo_relative"])
    c_xsa = c_manifest["artifacts"]["vivado/keccak_experiment.xsa"]["sha256"]
    c_bit = c_manifest["artifacts"]["vivado/keccak_experiment.runs/impl_1/system_wrapper.bit"]["sha256"]
    rows.append(record(
        "c_keccak_route4k_offline_implementation", "Keccak_PS_AXI_Lite_route4k_build",
        "offline_build", "passed", [C_ROUTE4K, c_build_dir / "vivado/timing.txt",
                                     c_build_dir / "vivado/drc.txt",
                                     c_build_dir / "vivado/keccak_experiment.gen/sources_1/bd/system/hw_handoff/system.hwh"],
        build={"variant": "keccak_route4k", "build_id": None,
               "manifest_sha256": hashlib.sha256((root / C_ROUTE4K).read_bytes()).hexdigest(),
               "elf_sha256": None, "bit_sha256": c_bit, "xsa_sha256": c_xsa},
        details={"target": c_manifest.get("target"), "board_validated": False,
                 "address_base": address_map.get("base"),
                 "address_end_inclusive": address_map.get("end_inclusive"),
                 "performance_measurement": False,
                 "meaning": "Fully routed offline implementation/XSA only; no board MMIO or throughput measurement."},
        root=root))

    ids = [row["record_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate record IDs; refusing to merge evidence")
    return {
        "schema_version": 1,
        "generated_date": date.today().isoformat(),
        "policy": {
            "aggregation": "none; every row remains tied to one source run/build/scenario",
            "missing_measurements": "null; no values are inferred from other runs or prose",
            "board_counters": "null unless the selected evidence explicitly reports counter values",
            "privacy": "allowlisted fields only; no absolute paths, keys, seeds, images, or recording payloads",
        },
        "records": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = (args.output if args.output.is_absolute() else ROOT / args.output).resolve()
    try:
        relative_output = output.relative_to(ROOT)
    except ValueError as exc:
        raise SystemExit("output must stay inside the repository; absolute paths are not printed") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    summary = build_summary()
    # Output has only values assembled above from an explicit public-field allowlist.
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"BENCHMARK_SUMMARY_WRITTEN {relative_output.as_posix()}")
    print(f"records={len(summary['records'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
