"""Audit two fixed G7 batches and emit a sanitized, reproducible snapshot.

Requires the ignored local evidence and exact candidate006d build. Does not
access the board, scan for newer runs, or expose session IDs/key fingerprints.
"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc/src/host"))
from build_manifest import verify

WORKSPACE = ROOT / "build/vitis/g6_auto_recovery_20261009_candidate006d"
MANIFEST_SHA = "0eb922b903f4f87b555a09cce67e928d5a910a37ece3ba359aebe055ffe28abc"
BUILD = {
    "manifest_sha256": MANIFEST_SHA,
    "elf_sha256": "e93ad4b6551bb993821a8e396d8f4c4c1f40c6bd6292247391ff129a0d9e8051",
    "xsa_sha256": "46de12fa970aaa203b5f99f875a158bf12f3a1bab6bc2b82faad294a40c01024",
}
BATCHES = (
    ("camera-reset", "g7_auto_recovery_camera-reset_20261009_130040_000419_94c71338"),
    ("routing-stall", "g7_auto_recovery_routing-stall_20261009_130631_779051_71ff6ed5"),
)
SHORT = ROOT / "data/captures/g6_usb_20261009_205804_775591/result.json"
OUTPUT = ROOT / "report/g7_candidate006d_acceptance_20261010.json"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    path = Path(path).resolve()
    require(path.is_relative_to(ROOT), "Evidence path outside repository")
    return json.loads(path.read_text(encoding="utf-8"))


def source(path):
    path = Path(path).resolve()
    require(path.is_relative_to(ROOT), "Evidence path outside repository")
    return {"path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    manifest_path = WORKSPACE / "g6_usb_manifest.json"
    require(source(manifest_path)["sha256"] == MANIFEST_SHA, "Manifest identity changed")
    manifest, count = verify(WORKSPACE, "g6_usb_manifest.json")
    require(count == 180, "Unexpected manifest verification count")
    require(manifest["variant"] == "g6-auto-camera-dma-recovery-usb-bounded-candidate-v4",
            "Unexpected candidate variant")
    short = read(SHORT)
    require(short["status"] == "passed" and short["build"] == BUILD, "Short baseline mismatch")
    require(len(short["sessions"]) == 1, "Short baseline must contain one session")
    s = short["sessions"][0]
    require(s["frames"] == s["observed_verified_frames"] == 471, "Short frame mismatch")
    require(s["bytes"] == s["observed_verified_bytes"] == 4659270, "Short byte mismatch")
    require(s["packets"] == s["errors"]["authenticated_packets"] ==
            s["errors"]["grouped_packets"] == 3768, "Short authentication mismatch")
    result = {
        "schema_version": 1, "snapshot_date": "2026-10-10",
        "measurement_date": "2026-10-09", "variant": manifest["variant"],
        "build": BUILD, "manifest_checks_passed": count,
        "manifest_board_validated_at_build": manifest["board_validated"],
        "build_source": source(manifest_path),
        "short_baseline": {
            "status": "passed", "seconds": s["seconds"], "frames": s["frames"],
            "bytes": s["bytes"], "fps": s["fps"], "authenticated_packets": 3768,
            "board_counters": short.get("board_counters"), "source": source(SHORT)},
        "batches": [], "g7_overall": "incomplete",
        "same_build_pending": ["receiver-exit/DTR 20 trials", "physical USB unplug 20 trials"],
        "scope": {
            "faults": "Controlled PL camera reset/PWDN and controlled PL routing stall",
            "timeout": "Real S2MM Busy reaches a software deadline; not a hardware timeout IRQ",
            "physical_camera_unplug_tested": False, "two_hour_run_measured": False,
            "current_device_state_checked": False,
            "raw_evidence_in_git": False,
            "fault_receiver_status": "running checkpoint; harness stops its own live reader after firmware recovery",
        },
    }
    for mode, directory in BATCHES:
        folder = ROOT / "report/g7_runs" / directory
        batch_path = folder / "batch_summary.json"
        batch = read(batch_path)
        require(batch["status"] == "passed" and batch["mode"] == mode and
                batch["attempts_requested"] == len(batch["trials"]) == 20, "Batch not complete")
        require(batch["variant"] == manifest["variant"] and
                batch["xsa_sha256"] == BUILD["xsa_sha256"], "Batch build mismatch")
        require(Path(batch["workspace"]).resolve() == WORKSPACE.resolve(), "Batch workspace mismatch")
        require(batch["jtag_loads"] == 1 and batch["jtag_reloads_between_trials"] is False,
                "Unexpected JTAG reload")
        rows, sessions, fingerprints = [], set(), set()
        for number, brief in enumerate(batch["trials"], 1):
            trial_path = folder / f"trial_{number:02d}" / "trial.json"
            t = read(trial_path)
            prefix = f"{mode} trial {number}: "
            require(t["trial"] == number and t["status"] == brief["status"] == "passed" and
                    t["mode"] == mode and t["build"] == BUILD, prefix + "identity/status mismatch")
            require(t["jtag_load_before"] == (number == 1) and
                    t["jtag_reload_after_initial_load"] is False and
                    t["jtag_reload_for_recovery"] is False, prefix + "JTAG reload")
            require(t["fault_receiver_live_before_trigger"] is True and
                    t["pre_trigger_health"]["worker_live"] is True and t["fresh_hello"] is True,
                    prefix + "live/HELLO evidence missing")
            require(t["old_session_id"] != t["new_session_id"] and
                    t["old_video_key_sha256"] != t["new_video_key_sha256"], prefix + "session/key reused")
            require(t["old_session_id"] == brief["old_session_id"] and
                    t["new_session_id"] == brief["new_session_id"] and
                    t["old_video_key_sha256"] == brief["old_key_sha256"] and
                    t["new_video_key_sha256"] == brief["new_key_sha256"], prefix + "summary novelty mismatch")
            sessions.update((t["old_session_id"], t["new_session_id"]))
            fingerprints.update((t["old_video_key_sha256"], t["new_video_key_sha256"]))
            b = t["board_telemetry"]
            require(b["busy_start"] == b["busy_deadline"] == 1 and
                    3000000 <= b["elapsed_us"] <= 3000100 and b["recovery_status"] == 0,
                    prefix + "Busy/deadline/recovery mismatch")
            # camera_status is a raw camera register, not an XST_SUCCESS return code.
            deltas = {name: b[name + "_after"] - b[name + "_before"]
                      for name in ("capture", "dropped", "fatal", "control", "transport")}
            require(deltas == {"capture": 1, "dropped": 1, "fatal": 0, "control": 0,
                               "transport": 0}, prefix + "unexpected counter delta")
            require(b["send_status"] == b["resume_status"] == 0, prefix + "USB status failure")
            health = t["post_stop_health"]
            require(health["fatal"] == b["fatal_after"] and health["control"] == b["control_after"] and
                    health["transport"] == b["transport_after"] and
                    health["send_status"] == health["resume_status"] == 0,
                    prefix + "post-stop errors")
            receiver_path = Path(t["recovery_receiver_result"])
            receiver = read(receiver_path)
            require(receiver["status"] == "passed" and receiver["build"] == BUILD and
                    len(receiver["sessions"]) == 1, prefix + "recovery receiver mismatch")
            rs = receiver["sessions"][0]
            require(rs["frames"] == rs["observed_verified_frames"] ==
                    t["verified_recovery_frames"] == brief["frames_after_recovery"] and
                    rs["frames"] > 0, prefix + "authenticated frame mismatch")
            require(rs["errors"]["authenticated_packets"] == rs["errors"]["grouped_packets"] > 0,
                    prefix + "authentication count mismatch")
            require(t["verified_frames_before_fault"] == brief["frames_before_fault"] > 0 and
                    b["elapsed_us"] == brief["elapsed_us"], prefix + "summary metric mismatch")
            rows.append({"trial": number, "status": "passed", "session_changed": True,
                         "key_changed": True, "fresh_hello": True, "receiver_live_before_fault": True,
                         "frames_before_fault": t["verified_frames_before_fault"],
                         "frames_after_recovery": rs["frames"], "busy_deadline_elapsed_us": b["elapsed_us"],
                         "counter_deltas": deltas, "jtag_reload_for_recovery": False,
                         "sources": [source(trial_path), source(receiver_path)]})
        require(len(sessions) == len(fingerprints) == 40, "Within-batch session/key uniqueness mismatch")
        result["batches"].append({"mode": mode, "status": "passed", "passed": 20,
                                 "requested": 20, "jtag_loads": 1,
                                 "jtag_reloads_between_trials": False,
                                 "unique_session_count": 40, "unique_key_fingerprint_count": 40,
                                 "completed_utc": batch["completed_utc"],
                                 "source": source(batch_path), "trials": rows})
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Manifest 180 checks; camera-reset 20/20; routing-stall 20/20; sanitized snapshot written.")


if __name__ == "__main__":
    main()
