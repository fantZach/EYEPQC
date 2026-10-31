"""Offline package checks only; no Linux deployment or network acceptance."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_candidate as candidate


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'server.zip'

    def test_exact_source_allowlist_hashes_and_pending_status(self):
        summary = candidate.package(self.output)
        self.assertEqual(summary['sha256'], hashlib.sha256(self.output.read_bytes()).hexdigest())
        self.assertFalse(summary['deployment_performed'])
        with ZipFile(self.output) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(set(archive.namelist()), {*candidate.FILES, 'manifest.json', 'SHA256SUMS.txt'})
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['user_acceptance'], 'pending')
            for flag in ('linux_sshd_validated', 'systemd_validated', 'public_network_validated',
                         'deployment_performed', 'runtime_keys_or_configuration_included'):
                self.assertIs(manifest[flag], False)
            for name, digest in manifest['source_sha256'].items():
                self.assertEqual(digest, hashlib.sha256(archive.read(name)).hexdigest())
            for line in archive.read('SHA256SUMS.txt').decode().splitlines():
                digest, name = line.split('  ', 1)
                self.assertEqual(digest, hashlib.sha256(archive.read(name)).hexdigest())

    def test_unlisted_runtime_files_are_not_read_or_copied(self):
        sources = self.root / 'source'
        sources.mkdir()
        for name in candidate.FILES:
            path = sources / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('public fixture')
        for name in ('authorized_keys', 'sshd_config', 'ssh_host_ed25519_key', 'login.txt'):
            (sources / name).write_text('must-not-export-fixture')
        with patch.object(candidate, 'ROOT', sources):
            candidate.package(self.output)
        with ZipFile(self.output) as archive:
            self.assertFalse(any(b'must-not-export-fixture' in archive.read(name)
                                 for name in archive.namelist()))

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b'keep original')
        with self.assertRaises(FileExistsError):
            candidate.package(self.output)
        self.assertEqual(self.output.read_bytes(), b'keep original')

    def test_missing_source_creates_no_partial_output(self):
        with patch.object(candidate, 'ROOT', self.root / 'absent'), self.assertRaises(FileNotFoundError):
            candidate.package(self.output)
        self.assertFalse(self.output.exists())

    def test_linked_paths_and_non_zip_outputs_rejected(self):
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ValueError):
            candidate.package(self.output)
        with self.assertRaises(ValueError):
            candidate.package(self.root / 'not-an-archive.txt')
        self.assertFalse(self.output.exists())

    def test_network_paths_rejected_before_any_filesystem_access(self):
        with patch.object(candidate.os.path, 'abspath', side_effect=AssertionError('must not probe network')):
            for path in ('//example.invalid/share/server.zip', '\\\\example.invalid\\share\\server.zip'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    candidate.package(path)

    def test_reproducible_source_package(self):
        candidate.package(self.output)
        other = self.root / 'other.zip'
        candidate.package(other)
        self.assertEqual(self.output.read_bytes(), other.read_bytes())


if __name__ == '__main__':
    unittest.main()
