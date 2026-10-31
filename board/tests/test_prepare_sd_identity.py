"""Synthetic local preparation only: no real user identity, SD card or hardware."""

import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import struct
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'board/prj'))
import prepare_sd_identity as sd


class PrepareSdTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / 'prepared'

    def existing_identity(self):
        source = self.root / 'existing'
        source.mkdir(mode=0o700)
        sd.private_acl(source, protect=True)
        public, key = sd.ML_KEM_512.key_derive(bytes(range(64)))
        path = source / 'identity.bin'
        descriptor = sd.os.open(path, sd.os.O_WRONLY | sd.os.O_CREAT | sd.os.O_EXCL, 0o600)
        with sd.os.fdopen(descriptor, 'wb') as handle:
            handle.write(key)
        sd.private_acl(path)
        return path, public, key

    def test_new_materials_match_firmware_format_and_real_kem(self):
        record = sd.prepare(self.output)
        private = self.output / 'private'
        key = (private / sd.KEY_NAME).read_bytes()
        public = (self.output / 'public/public.bin').read_bytes()
        self.assertEqual(sd.validate_key(key), public)
        self.assertEqual(len(key), 1632)
        self.assertEqual(record['public_key_sha256'], hashlib.sha256(public).hexdigest())
        self.assertEqual((self.output / 'public/public.sha256').read_text().strip(), record['public_key_sha256'])
        state0, state1 = [(private / name).read_bytes() for name in sd.STATE_NAMES]
        self.assertEqual(state0, state1)
        self.assertEqual(len(state0), 80)
        self.assertEqual(struct.unpack('!8sQ', state0[:16]), (b'EYERNG01', 0))
        self.assertEqual(state0[48:], hashlib.sha256(state0[:48]).digest())
        self.assertEqual({p.name for p in private.iterdir()}, {sd.KEY_NAME, *sd.STATE_NAMES})
        self.assertEqual({p.name for p in (self.output / 'public').iterdir()}, {'public.bin', 'public.sha256'})
        self.assertFalse(record['sd_card_written'])
        self.assertFalse(record['host_seed_injection_required'])
        self.assertFalse(record['production_security_accepted'])
        self.assertTrue(record['preparation_pc_knew_private_material'])

    def test_explicit_reuse_preserves_identity_but_generates_independent_state(self):
        path, public, key = self.existing_identity()
        with patch.object(sd.ML_KEM_512, 'key_derive') as derive, patch.object(sd.os, 'urandom', return_value=b'R' * 32) as random:
            record = sd.prepare(self.output, path)
        derive.assert_not_called()
        random.assert_called_once_with(32)
        self.assertEqual((self.output / 'private/EYEKEY.BIN').read_bytes(), key)
        self.assertEqual((self.output / 'public/public.bin').read_bytes(), public)
        self.assertEqual((self.output / 'private/EYERNG0.BIN').read_bytes()[16:48], b'R' * 32)
        self.assertEqual(path.read_bytes(), key)
        self.assertEqual(record['identity_source'], 'explicit-existing-key')

    def test_directory_acl_failure_precedes_secret_generation(self):
        with patch.object(sd, 'private_acl', side_effect=PermissionError('fixture')), patch.object(sd.os, 'urandom') as random:
            with self.assertRaises(PermissionError):
                sd.prepare(self.output)
        random.assert_not_called()
        self.assertEqual(list((self.output / 'private').iterdir()), [])

    def test_every_file_acl_checked_before_randomness(self):
        actual = sd.private_acl
        def acl(path, **kwargs):
            if Path(path).name == sd.STATE_NAMES[1]:
                raise PermissionError('fixture')
            actual(path, **kwargs)
        with patch.object(sd, 'private_acl', new=acl), patch.object(sd.os, 'urandom') as random:
            with self.assertRaises(PermissionError):
                sd.prepare(self.output)
        random.assert_not_called()
        self.assertTrue(all(path.stat().st_size == 0 for path in (self.output / 'private').iterdir()))

    def test_existing_and_unsafe_paths_rejected_without_randomness(self):
        self.output.mkdir()
        marker = self.output / 'keep'
        marker.write_bytes(b'original')
        with patch.object(sd.os, 'urandom') as random:
            with self.assertRaises(FileExistsError):
                sd.prepare(self.output)
            for path in ('relative', r'\\server\share\new'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    sd.prepare(path)
            with patch.object(Path, 'is_symlink', return_value=True), self.assertRaises(ValueError):
                sd.prepare(self.root / 'linked')
        random.assert_not_called()
        self.assertEqual(marker.read_bytes(), b'original')

    def test_import_acl_rejection_does_not_create_output(self):
        path, _, _ = self.existing_identity()
        with patch.object(sd, 'private_acl', side_effect=PermissionError('fixture')), patch.object(sd.os, 'urandom') as random:
            with self.assertRaises(PermissionError):
                sd.prepare(self.output, path)
        random.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_corrupt_import_length_hash_or_private_component_rejected(self):
        path, _, key = self.existing_identity()
        for index, bad in enumerate((key[:-1], key + b'x', bytes(1632), bytes([key[0] ^ 1]) + key[1:])):
            path.write_bytes(bad)
            output = self.root / ('bad' + str(index))
            with self.subTest(index=index), self.assertRaises(ValueError):
                sd.prepare(output, path)
            self.assertFalse((output / 'public').exists())
            self.assertTrue(all(p.stat().st_size == 0 for p in (output / 'private').iterdir()))

    def test_cli_does_not_print_secret_or_source_path(self):
        path, _, key = self.existing_identity()
        out, err = io.StringIO(), io.StringIO()
        with patch.object(sd.os, 'urandom', return_value=b'X' * 32), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(sd.main(['--output', str(self.output), '--identity-file', str(path)]), 0)
        text = out.getvalue() + err.getvalue()
        self.assertNotIn(key.hex(), text)
        self.assertNotIn(base64.b64encode(key).decode(), text)
        self.assertNotIn((b'X' * 32).hex(), text)
        self.assertNotIn(str(path), text)
        self.assertEqual(json.loads(out.getvalue())['user_acceptance'], 'pending')

    def test_failure_preserves_protected_files_and_erases_owned_buffers(self):
        erased = []
        actual = sd.erase
        def erase(value):
            actual(value)
            if value is not None:
                erased.append(value)
        with patch.object(sd, 'write_new', side_effect=OSError('fixture')), patch.object(sd, 'erase', new=erase):
            with self.assertRaises(OSError):
                sd.prepare(self.output)
        self.assertTrue(all(not any(value) for value in erased))
        self.assertTrue((self.output / 'private/EYEKEY.BIN').is_file())
        sd.private_acl(self.output / 'private/EYEKEY.BIN')
        self.assertFalse((self.output / 'identity.json').exists())

    def test_python_preparation_opens_and_advances_in_real_c_implementation(self):
        compiler = next((path for path in (shutil.which('gcc'), shutil.which('clang'),
                        'C:/msys64/ucrt64/bin/gcc.exe') if path and Path(path).is_file()), None)
        self.assertTrue(compiler, 'A native GCC or Clang compiler is required')
        executable = self.root / 'sd-state-files.exe'
        command = [compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                   '-I', str(ROOT / 'board/src/ps/include'),
                   '-I', str(ROOT / 'board/src/third_party/tinycrypt/lib/include')]
        command += [str(ROOT / source) for source in (
            'board/tests/sd_state_file_harness.c', 'board/src/ps/src/g6_sd_state.c',
            'board/src/ps/src/g6_hmac_drbg.c', 'board/src/ps/src/session.c',
            'board/src/ps/src/protocol.c', 'board/src/third_party/tinycrypt/lib/source/sha256.c',
            'board/src/third_party/tinycrypt/lib/source/utils.c')]
        built = subprocess.run(command + ['-o', str(executable)], capture_output=True, text=True, timeout=30)
        self.assertEqual(built.returncode, 0, built.stderr)
        sd.prepare(self.output)
        slots = [self.output / 'private' / name for name in sd.STATE_NAMES]
        outputs = []
        for generation in range(1, 4):
            sample = self.root / ('output' + str(generation) + '.bin')
            result = subprocess.run([str(executable), *map(str, slots),
                                     str(self.output / 'public/public.bin'), str(sample)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('SD_STATE_FILE_PASS generation=' + str(generation), result.stdout)
            states = [slot.read_bytes() for slot in slots]
            self.assertEqual(sorted(struct.unpack('!Q', state[8:16])[0] for state in states),
                             [generation - 1, generation])
            for state in states:
                self.assertEqual(state[48:], hashlib.sha256(state[:48]).digest())
            outputs.append(sample.read_bytes())
        self.assertEqual({len(output) for output in outputs}, {64})
        self.assertEqual(len(set(outputs)), 3)
        broken = bytearray(slots[0].read_bytes())
        broken[20] ^= 1
        slots[0].write_bytes(broken)
        sample = self.root / 'must-not-exist.bin'
        result = subprocess.run([str(executable), *map(str, slots),
                                 str(self.output / 'public/public.bin'), str(sample)],
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(sample.exists())


if __name__ == '__main__':
    unittest.main()
