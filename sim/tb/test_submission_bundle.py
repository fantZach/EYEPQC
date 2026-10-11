"""Focused policy and ZIP integrity tests for the submission bundle builder."""

from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from prj.prepare_submission_bundle import (
    BundleError,
    EVIDENCE_STATUS,
    INDEX_NAME,
    BUNDLE_NAME,
    ROOT,
    selected_paths,
    is_explicit_extra_candidate,
    is_forbidden_path,
    is_public_candidate,
    deterministic_zip_info,
    json_bytes,
    normalize_repo_path,
    sha256_bytes,
    verify_zip,
)


class SubmissionBundlePolicyTests(unittest.TestCase):
    def test_current_candidate014_status_and_evidence_are_included(self):
        statuses = {entry["id"]: entry for entry in EVIDENCE_STATUS}
        self.assertEqual(statuses["g7_overall"]["status"], "not_passed")
        self.assertEqual(
            statuses["g7_candidate014_receiver_exit"]["status"],
            "offline_candidate_board_validation_pending",
        )
        self.assertEqual(
            statuses["g7_candidate012_receiver_exit"]["status"],
            "failed_batch_13_of_20",
        )
        self.assertEqual(
            statuses["competition_requirements"]["status"],
            "generic_schedule_verified_track_rules_pending",
        )
        self.assertEqual(
            statuses["computer_only_regression_20261011"]["status"],
            "passed_19_of_19_offline",
        )
        self.assertEqual(
            statuses["full_sim_regression_20261011"]["status"],
            "passed_133_of_133_offline",
        )
        self.assertEqual(statuses["production_security"]["status"], "not_passed")
        selected, _, _ = selected_paths(ROOT, [])
        selected_set = set(selected)
        for entry in EVIDENCE_STATUS:
            with self.subTest(evidence=entry["evidence"]):
                self.assertIn(entry["evidence"], selected_set)
        self.assertIn(
            "report/g7_candidate014_safe_hello_ack_retry_offline_20261011.md",
            selected_set,
        )
        self.assertIn("report/contest_rules_review_20261011.md", selected_set)
        self.assertIn("report/software_regression_20261011.md", selected_set)
        self.assertIn("report/production_security_profile_20261011.md", selected_set)
        self.assertIn("src/ps/src/g6_hmac_drbg.c", selected_set)
        self.assertIn("src/ps/include/g6_hmac_drbg.h", selected_set)
        self.assertIn("sim/tb/test_g6_hmac_drbg.c", selected_set)

    def test_review_bundle_names_are_current_and_not_formal_submission_names(self):
        self.assertEqual(BUNDLE_NAME, "EYEPQC_submission_review_candidate014_20261011.zip")
        self.assertEqual(INDEX_NAME, "evidence_index_candidate014_20261011.json")

    def test_fixed_exclusions_and_known_public_kat(self):
        excluded = (
            "build/vitis/image.elf",
            "data/captures/private.jpg",
            "report/g7_runs/raw.json",
            ".venv/lib/site.py",
            "local/localkey.bin",
            "prj/g6_seed.bin",
            "src/private/device_private_key.txt",
            "camera/session.mp4",
        )
        for path in excluded:
            with self.subTest(path=path):
                self.assertTrue(is_forbidden_path(path))
                self.assertFalse(is_public_candidate(path))

        # Public NIST known-answer vectors are deliberately allowed; their
        # test secrets are public vector data, never provisioning inputs.
        self.assertTrue(is_public_candidate("data/kat/nist_mlkem512.json"))
        self.assertTrue(is_public_candidate("data/kat/nist_gcm.json"))

    def test_future_files_need_safe_explicit_allowlist_shape(self):
        self.assertTrue(is_explicit_extra_candidate("report/keccak_board_acceptance.md"))
        self.assertTrue(is_explicit_extra_candidate("prj/parse_keccak_board_result.py"))
        self.assertTrue(is_explicit_extra_candidate("prj/run_keccak_benchmark_jtag.tcl"))
        self.assertFalse(is_explicit_extra_candidate("prj/private/seed.tcl"))
        self.assertFalse(is_explicit_extra_candidate("report/g7_runs/raw.json"))
        self.assertFalse(is_explicit_extra_candidate("src/ps/new_secret.c"))

    def test_rejects_traversal_and_absolute_paths(self):
        for path in ("../outside.txt", "src/../../outside.txt", r"..\outside.txt", r"C:\outside.txt", "/outside.txt"):
            with self.subTest(path=path):
                with self.assertRaises(BundleError):
                    normalize_repo_path(path)

    def test_zip_roundtrip_and_rejects_corruption_or_missing_member(self):
        payload_path = "docs/example.md"
        payload = b"public sample evidence\n"
        payload_hash = sha256_bytes(payload)
        manifest_path = "META/content_manifest.json"
        manifest = json_bytes({"files": [{"path": payload_path, "sha256": payload_hash}]})
        expected = {
            payload_path: payload_hash,
            manifest_path: sha256_bytes(manifest),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            good = root / "good.zip"
            with ZipFile(good, "w") as archive:
                archive.writestr(deterministic_zip_info(payload_path), payload)
                archive.writestr(deterministic_zip_info(manifest_path), manifest)
            self.assertEqual(verify_zip(good, expected), expected)

            corrupted = root / "corrupted.zip"
            with ZipFile(corrupted, "w") as archive:
                archive.writestr(deterministic_zip_info(payload_path), b"changed\n")
                archive.writestr(deterministic_zip_info(manifest_path), manifest)
            with self.assertRaises(BundleError):
                verify_zip(corrupted, expected)

            missing = root / "missing.zip"
            with ZipFile(missing, "w") as archive:
                archive.writestr(deterministic_zip_info(manifest_path), manifest)
            with self.assertRaises(BundleError):
                verify_zip(missing, expected)


if __name__ == "__main__":
    unittest.main()
