import json
import re
import tempfile
import unittest
from pathlib import Path

from board.prj.collect_benchmark_summary import (
    C_ROUTE4K, DEMO_CAPTURE, DEMO_RESULT, G0_LOG, G0_MANIFEST, G0_RESULT,
    G3_RESULTS, G6_RESULT, G7_RESULTS, VALIDATION_SNAPSHOT, build_summary, record,
)


class BenchmarkSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._write(G0_MANIFEST, {"application": "fixture", "build_id": "fixture-build",
                                  "board_validated": False})
        self._write(G0_RESULT, {"status": "passed", "build_ids": ["fixture-build"],
                                "final_uptime_s": 30, "boot_modes": [0], "boot_count": 1,
                                "stat_samples": 3, "final_ddr_passes": 2})
        self._write(G0_LOG, {"line": "G0 STAT uptime_s=30 ticks=300 ddr_pass=2 ddr_err=0 "
                                   "assert=0 exception=0 timer_err=0 boot_mode=0x00"})
        for index, relative in enumerate(G3_RESULTS, start=1):
            self._write(relative, {"board_validated": True, "vts": 30, "runs": [{
                "frames": 20 * index, "queued": 20 * index, "sent": 20 * index,
                "dropped": 0, "overflows": 0, "elapsed_us": 1_000_000 * index,
                "fps": 20.0, "total_bytes": 1000 * index, "packet_count": 20 * index,
            }]})
        self._write(G6_RESULT, {"status": "passed", "board_counters": None,
                                "build": {}, "sessions": [{"seconds": 3, "frames": 4,
                                "fps": 1.3, "bytes": 800, "packets": 4, "errors": {}}]})
        self._write(DEMO_RESULT, {"status": "passed", "board_accessed": True,
                                  "recording_seconds": 15, "recording_frames": 722,
                                  "recording_fps": 48.1, "recording_exported_frame_count": 722,
                                  "recorder_callback_frames": "722/722"})
        self._write(DEMO_CAPTURE, {"board_counters": None, "build": {}})
        for index, (record_id, _scenario, relative) in enumerate(G7_RESULTS):
            status = "passed" if index == 0 else "failed"
            self._write(relative, {"variant": record_id, "attempts_requested": 1,
                                   "xsa_sha256": None, "trials": [{"status": status,
                                   "frames_before_fault": 100, "frames_after_recovery": 4,
                                   "elapsed_us": 2000}]})
        self._write(VALIDATION_SNAPSHOT, {"offline_candidate_validation": {
            "board_accessed": False, "board_validated": False, "variant": "offline-fixture",
            "result": "built"}})
        c_build_dir = Path("build/parallel_20261009/C/route4k")
        c_xsa_rel = c_build_dir / "vivado/keccak_experiment.xsa"
        c_bit_rel = c_build_dir / "vivado/keccak_experiment.runs/impl_1/system_wrapper.bit"
        c_timing_rel = c_build_dir / "vivado/timing.txt"
        c_drc_rel = c_build_dir / "vivado/drc.txt"
        c_hwh_rel = c_build_dir / "vivado/keccak_experiment.gen/sources_1/bd/system/hw_handoff/system.hwh"
        for relative, body in ((c_xsa_rel, "fixture xsa"), (c_bit_rel, "fixture bit"),
                               (c_timing_rel, "fixture timing"), (c_drc_rel, "fixture drc"),
                               (c_hwh_rel, "fixture hwh")):
            self._write(relative, body)
        import hashlib
        self._write(C_ROUTE4K, {
            "output_location_repo_relative": c_build_dir.as_posix(),
            "target": "xc7z020clg400-2",
            "source_sha256": {},
            "artifacts": {
                "vivado/keccak_experiment.xsa": {"sha256": hashlib.sha256(b"fixture xsa").hexdigest()},
                "vivado/keccak_experiment.runs/impl_1/system_wrapper.bit": {"sha256": hashlib.sha256(b"fixture bit").hexdigest()},
                "vivado/timing.txt": {"sha256": hashlib.sha256(b"fixture timing").hexdigest()},
                "vivado/drc.txt": {"sha256": hashlib.sha256(b"fixture drc").hexdigest()},
            },
            "address_map": {"keccak_axi_lite": {"base": "0x43C10000",
                "end_inclusive": "0x43C10FFF"}},
        })

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, dict):
            path.write_text(json.dumps(value), encoding="utf-8")
        else:
            path.write_text(str(value), encoding="utf-8")

    def _read(self, relative):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def summary(self):
        # Fixture validation bypasses only the real manifest hash checker; the exact
        # production summary extraction/record-building path still runs.
        return build_summary(self.root, manifest_validator=lambda _path: None)

    def test_build_and_scenario_rows_stay_separate_without_cross_run_aggregation(self):
        rows = self.summary()["records"]
        ids = [row["record_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)))
        by_id = {row["record_id"]: row for row in rows}
        self.assertNotEqual(by_id["g7_camera_reset_candidate7_single"]["scenario"],
                            by_id["g7_routing_stall_candidate6_single"]["scenario"])
        self.assertEqual(by_id["g3_fast_run_1"]["frames"], 20)
        self.assertEqual(by_id["g3_fast_run_2"]["frames"], 40)
        self.assertEqual(by_id["g3_fast_run_1"]["fps"], 20.0)
        self.assertEqual(by_id["g3_fast_run_2"]["fps"], 20.0)
        self.assertNotEqual(by_id["g3_fast_run_1"]["sources"], by_id["g3_fast_run_2"]["sources"])
        self.assertIsNone(by_id["g7_camera_reset_candidate7_single"]["fps"])

    def test_failed_g7_trial_is_preserved_as_failed(self):
        rows = {row["record_id"]: row for row in self.summary()["records"]}
        failed = rows["g7_routing_stall_candidate6_single"]
        self.assertEqual(failed["outcome"], "failed")
        self.assertEqual(failed["evidence_class"], "unknown")

    def test_explicit_failed_g3_status_cannot_pass_on_good_counters(self):
        result = self._read(G3_RESULTS[0])
        result["status"] = "failed"
        self._write(G3_RESULTS[0], result)
        rows = {row["record_id"]: row for row in self.summary()["records"]}
        self.assertEqual(rows["g3_fast_run_1"]["outcome"], "failed")
        self.assertTrue(rows["g3_fast_run_1"]["details"]["source_status_recorded"])
        self.assertEqual(rows["g3_fast_run_1"]["details"]["source_status"], "failed")

    def test_legacy_g3_without_status_uses_counters_and_marks_status_missing(self):
        result = self._read(G3_RESULTS[0])
        result.pop("status", None)
        self._write(G3_RESULTS[0], result)
        row = next(row for row in self.summary()["records"] if row["record_id"] == "g3_fast_run_1")
        self.assertEqual(row["outcome"], "passed")
        self.assertFalse(row["details"]["source_status_recorded"])
        self.assertEqual(row["details"]["source_status"], "not_recorded")

    def test_keccak_is_offline_build_not_a_performance_measurement(self):
        row = next(row for row in self.summary()["records"]
                   if row["record_id"] == "c_keccak_route4k_offline_implementation")
        self.assertEqual(row["evidence_class"], "offline_build")
        self.assertEqual(row["build"]["variant"], "keccak_route4k")
        self.assertEqual(row["details"]["address_base"], "0x43C10000")
        self.assertIs(row["details"]["board_validated"], False)
        self.assertIsNone(row["frames"])
        self.assertIsNone(row["fps"])
        self.assertIsNone(row["bytes"])

    def test_keccak_artifact_hash_mismatch_fails_closed(self):
        path = self.root / "build/parallel_20261009/C/route4k/vivado/keccak_experiment.xsa"
        path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "build artifact hash mismatch"):
            self.summary()

    def test_unread_counters_and_missing_values_remain_null(self):
        rows = {row["record_id"]: row for row in self.summary()["records"]}
        g6 = rows["g6_usb_20261008_one_session"]
        self.assertIsNone(g6["board_counters"])
        self.assertIsNone(g6["error_counts"])
        self.assertIsNone(g6["resolution"]["width"])
        self.assertIsNone(g6["resolution"]["height"])
        self.assertIsNone(rows["g7_camera_reset_candidate7_single"]["board_counters"])

    def test_offline_build_cannot_be_classified_as_physical_measurement(self):
        rows = {row["record_id"]: row for row in self.summary()["records"]}
        for record_id in ("g0_final2_offline_manifest_preflight",
                          "g6_usb_bounded_candidate_v3_offline_build"):
            row = rows[record_id]
            self.assertIn(row["evidence_class"], {"offline_artifact_check", "offline_build"})
            self.assertIsNone(row["frames"])
            self.assertIsNone(row["fps"])
            self.assertIsNone(row["bytes"])

    def test_public_rows_have_relative_sources_and_no_private_fields(self):
        summary = self.summary()
        serialized = str(summary)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotRegex(serialized, re.compile(r"\b[A-Za-z]:\\[^\s\"']+", re.IGNORECASE))
        self.assertNotRegex(serialized, re.compile(r"\b(private_key|secret_key|seed|cookie|token)\b", re.IGNORECASE))
        for row in summary["records"]:
            for source in row["sources"]:
                self.assertFalse(Path(source["path"]).is_absolute())
                self.assertNotIn("..", Path(source["path"]).parts)

    def test_untrusted_build_labels_and_result_strings_are_not_copied(self):
        g0 = self._read(G0_MANIFEST)
        g0["application"] = r"Z:\fixture_root\secret_key_build"
        g0["build_id"] = r"Z:\fixture_root\seed.bin"
        self._write(G0_MANIFEST, g0)
        g7 = self._read(G7_RESULTS[0][2])
        g7["variant"] = r"Z:\fixture_root\secret_key_build"
        self._write(G7_RESULTS[0][2], g7)
        snapshot = self._read(VALIDATION_SNAPSHOT)
        snapshot["offline_candidate_validation"]["variant"] = r"Z:\fixture_root\token_build"
        snapshot["offline_candidate_validation"]["result"] = r"Z:\fixture_root\seed.txt"
        self._write(VALIDATION_SNAPSHOT, snapshot)
        serialized = json.dumps(self.summary(), ensure_ascii=False)
        for private in ("Z:\\fixture_root", "secret_key_build", "seed.bin", "token_build"):
            self.assertNotIn(private, serialized)

    def test_missing_allowlisted_evidence_fails_closed(self):
        (self.root / G0_RESULT).unlink()
        with self.assertRaises(FileNotFoundError):
            self.summary()

    def test_record_rejects_absolute_evidence_path(self):
        with self.assertRaises(ValueError):
            record("bad_source", "scenario", "offline_build", "passed", [self.root / "secret.json"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
