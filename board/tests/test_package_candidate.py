"""Offline package guards; fake workspace and verifier, no media or hardware."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('package_candidate', ROOT / 'board/prj/package_candidate.py')
package_candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_candidate)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.output = self.root / 'candidate.zip'
        self.boot = self.workspace / package_candidate.BOOT
        self.boot.parent.mkdir(parents=True)
        self.boot.write_bytes(b'public-boot-fixture')
        for name in ['board/DEPLOYMENT.md', 'board/THIRD_PARTY_NOTICES.md', 'doc/g6_sd_identity.md',
                     *package_candidate.LICENSES.values(), 'sdk/Vitis/data/embeddedsw/license.txt']:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('Public notice fixture\n')
        self.summary = {'applications': ['g6_usb'], 'boot_images': True,
                        'g6_dev_usb_bootstrap': True, 'board_validated': False,
                        'generated_inputs': {'some-input': '0' * 64}, 'tool_root': str(self.root / 'sdk')}
        self.checked = {'status': 'PASS', 'board_accessed': False, 'board_validated': False,
                        'bsp_lookup': 'PASS', 'arm_startup': {'g6_usb': 'PASS', 'fsbl': 'PASS'},
                        'hash_checks': {'g6_usb': 79}, 'generated_input_checks': 1}
        self.manifest = {'application': 'g6_usb', 'security_profile': package_candidate.PROFILE,
                         'board_validated': False, 'development_provisioning_required': True,
                         'usb_bootstrap': {'identity_or_seed_embedded': False},
                         'xsa_sha256': '0' * 64, 'bsp_sha256': '1' * 64,
                         'artifacts': {package_candidate.BOOT: package_candidate.sha256(self.boot.read_bytes())}}
        self.save()
        self.addCleanup(patch.stopall)
        patch.object(package_candidate, 'ROOT', self.root).start()
        self.run = patch.object(package_candidate.subprocess, 'run',
                                return_value=subprocess.CompletedProcess([], 0)).start()
        self.verify = patch.object(package_candidate, 'verify', return_value=(self.manifest, 79)).start()

    def save(self):
        for name, data in [('software_build.json', self.summary), ('software_verification.json', self.checked),
                           ('g6_usb_manifest.json', self.manifest)]:
            (self.workspace / name).write_text(json.dumps(data))

    def call(self):
        return package_candidate.package(self.workspace, self.output)

    def test_allowlist_only_redacted_pending_and_fresh_verification(self):
        secret = 'DO-NOT-EXPORT-fixture-value'
        (self.workspace / 'private.bin').write_text(secret)
        self.manifest['private_password'] = secret
        self.manifest['xsa'] = str(self.root / 'local-input.xsa')
        self.save()
        result = self.call()
        self.assertEqual(result['user_acceptance'], 'pending')
        self.assertFalse(result['board_accessed'])
        self.assertEqual(self.run.call_args.args[0], [sys.executable,
                         str(self.root / 'board/prj/verify_software.py'), str(self.workspace)])
        with ZipFile(self.output) as archive:
            names = set(archive.namelist())
            self.assertEqual(names, {'BOOT.BIN', 'manifest.json', 'SHA256SUMS.txt', 'DEPLOYMENT.md',
                                    'THIRD_PARTY_NOTICES.md', 'licenses/amd_embeddedsw.txt',
                                    *package_candidate.LICENSES})
            public = json.loads(archive.read('manifest.json'))
            self.assertTrue(public['development_only'])
            self.assertTrue(public['local_use_only'])
            self.assertFalse(public['board_validated'])
            for name in names:
                self.assertNotIn(secret.encode(), archive.read(name))
                self.assertNotIn(str(self.root).encode(), archive.read(name))
            declared = dict((line.split('  ', 1)[1], line.split('  ', 1)[0])
                            for line in archive.read('SHA256SUMS.txt').decode().splitlines())
            self.assertEqual(set(declared), names - {'SHA256SUMS.txt'})
            for name, digest in declared.items():
                self.assertEqual(digest, package_candidate.sha256(archive.read(name)))

    def test_existing_output_is_never_overwritten_or_verified(self):
        self.output.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):
            self.call()
        self.run.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b'existing')

    def sd_profile(self):
        self.summary.update(g6_sd_identity=True, g6_dev_usb_bootstrap=False)
        self.manifest.update(security_profile=package_candidate.SD_PROFILE,
                             development_provisioning_required=False,
                             sd_identity={'identity_or_seed_embedded': False})
        self.save()

    def test_sd_identity_profile_exports_only_boot_public_docs_and_not_materials(self):
        self.sd_profile()
        for name in ('EYEKEY.BIN', 'EYERNG0.BIN', 'EYERNG1.BIN'):
            (self.workspace / name).write_bytes(b'SECRET-FIXTURE-NOT-FOR-EXPORT')
        self.call()
        with ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {
                'BOOT.BIN', 'manifest.json', 'SHA256SUMS.txt', 'DEPLOYMENT.md', 'SD_IDENTITY.md',
                'THIRD_PARTY_NOTICES.md', 'licenses/amd_embeddedsw.txt', *package_candidate.LICENSES})
            public = json.loads(archive.read('manifest.json'))
            self.assertEqual(public['security_profile'], package_candidate.SD_PROFILE)
            self.assertFalse(public['identity_or_seed_embedded'])
            self.assertFalse(public['board_validated'])
            for name in archive.namelist():
                self.assertNotIn(b'SECRET-FIXTURE-NOT-FOR-EXPORT', archive.read(name))
                self.assertNotIn(str(self.root).encode(), archive.read(name))

    def test_sd_profile_rejects_missing_flags_embedded_keys_and_bootstrap_mixture(self):
        self.sd_profile()
        for category, field, value in (
                ('summary', 'g6_sd_identity', False), ('summary', 'g6_dev_usb_bootstrap', True),
                ('manifest', 'development_provisioning_required', True),
                ('sd_identity', 'identity_or_seed_embedded', True)):
            with self.subTest(field=field):
                data = (self.summary if category == 'summary' else
                        self.manifest['sd_identity'] if category == 'sd_identity' else self.manifest)
                old = data[field]
                data[field] = value
                self.save()
                with self.assertRaises(ValueError):
                    self.call()
                self.assertFalse(self.output.exists())
                data[field] = old

    def test_linked_output_rejected_before_verification(self):
        with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ValueError):
            self.call()
        self.run.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_failed_fresh_check_rejects_historical_pass(self):
        self.run.return_value = subprocess.CompletedProcess([], 1)
        with self.assertRaises(ValueError):
            self.call()
        self.assertFalse(self.output.exists())

    def test_stale_source_and_boot_rejected(self):
        self.verify.side_effect = ValueError('stale source fixture')
        with self.assertRaises(ValueError):
            self.call()
        self.verify.side_effect = None
        self.boot.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.call()
        self.assertFalse(self.output.exists())

    def test_rejects_embedded_secrets_production_or_incomplete_checks(self):
        for mutate in [lambda: self.manifest.update(security_profile='external_provider_unvalidated'),
                       lambda: self.manifest['usb_bootstrap'].update(identity_or_seed_embedded=True),
                       lambda: self.checked.update(status='FAIL'),
                       lambda: self.checked.update(board_validated=True),
                       lambda: self.checked.update(hash_checks={'g6_usb': 78})]:
            with self.subTest(mutate=mutate):
                old_manifest = json.loads(json.dumps(self.manifest))
                old_checked = json.loads(json.dumps(self.checked))
                mutate()
                self.save()
                with self.assertRaises(ValueError):
                    self.call()
                self.assertFalse(self.output.exists())
                self.manifest.clear()
                self.manifest.update(old_manifest)
                self.checked = old_checked

    def test_rejects_workspace_output_and_missing_license(self):
        with self.assertRaises(ValueError):
            package_candidate.package(self.workspace, self.workspace / 'candidate.zip')
        (self.root / 'sdk/Vitis/data/embeddedsw/license.txt').unlink()
        with self.assertRaises(FileNotFoundError):
            self.call()
        self.assertFalse(self.output.exists())

    def test_sdk_internal_data_link_resolution_stays_inside_install(self):
        sdk_root = self.root / 'sdk'
        nominal = sdk_root / 'Vitis/data/embeddedsw/license.txt'
        target = sdk_root / 'data/embeddedsw/license.txt'
        target.parent.mkdir(parents=True)
        target.write_bytes(nominal.read_bytes())
        nominal.unlink()
        original = Path.resolve
        def resolve(path, *args, **kwargs):
            return target if path == nominal else original(path, *args, **kwargs)
        with patch.object(Path, 'resolve', new=resolve):
            self.call()
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.read('licenses/amd_embeddedsw.txt'), target.read_bytes())


if __name__ == '__main__':
    unittest.main()
