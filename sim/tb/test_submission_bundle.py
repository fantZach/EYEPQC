"""Focused policy and ZIP integrity tests for the submission bundle builder."""

from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from prj.prepare_submission_bundle import (
    BundleError,
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
