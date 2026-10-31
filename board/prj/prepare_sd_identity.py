"""Prepare private SD identity/state offline on a trusted PC; never write a card."""

import argparse
from contextlib import ExitStack
import hashlib
import hmac
import json
import os
from pathlib import Path
import struct
import sys

from prepare_dev_identity import erase, private_acl, write_new, ML_KEM_512

KEY_NAME = 'EYEKEY.BIN'
STATE_NAMES = ('EYERNG0.BIN', 'EYERNG1.BIN')


def local_path(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('Use an absolute local path')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('Paths must not traverse links')
    return path


def encode_state(secret, generation=0):
    if len(secret) != 32 or not 0 <= generation < 2**64:
        raise ValueError('Invalid SD random state')
    state = bytearray(80)
    struct.pack_into('!8sQ', state, 0, b'EYERNG01', generation)
    state[16:48] = secret
    state[48:] = hashlib.sha256(memoryview(state)[:48]).digest()
    return state


def validate_key(secret):
    if len(secret) != 1632:
        raise ValueError('Invalid ML-KEM-512 key length')
    public = bytes(memoryview(secret)[768:1568])
    if not hmac.compare_digest(memoryview(secret)[1568:1600], hashlib.sha3_256(public).digest()):
        raise ValueError('Invalid ML-KEM-512 public-key hash')
    # Check actual correspondence too: an embedded public key/hash alone cannot validate dkPKE.
    expected, ciphertext = ML_KEM_512.encaps(public)
    actual = ML_KEM_512.decaps(bytes(secret), ciphertext)
    if not hmac.compare_digest(expected, actual):
        raise ValueError('ML-KEM-512 key pair self-check failed')
    return public


def prepare(output, identity_file=None):
    output = local_path(output)
    if output.exists():
        raise FileExistsError('Never overwrite an existing preparation directory')
    if not output.parent.is_dir():
        raise ValueError('Output parent must already exist')
    source = local_path(identity_file) if identity_file is not None else None
    if source is not None:
        private_acl(source.parent)
        private_acl(source)
    output.mkdir(mode=0o700)
    private = output / 'private'
    private.mkdir(mode=0o700)
    private_acl(private, protect=True)
    seed = key = imported = random_secret = state = readback = None
    try:
        with ExitStack() as stack:
            targets = {}
            # Verify every inherited file ACL before creating or reading secret material.
            for name in (KEY_NAME, *STATE_NAMES):
                path = private / name
                descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
                targets[name] = stack.enter_context(os.fdopen(descriptor, 'w+b'))
                private_acl(path)
            if source is None:
                seed = bytearray(os.urandom(64))
                _, immutable_key = ML_KEM_512.key_derive(bytes(seed))
                key = bytearray(immutable_key)
                immutable_key = None
            else:
                imported = bytearray(1633)
                with source.open('rb', buffering=0) as handle:
                    if handle.readinto(imported) != 1632:
                        raise ValueError('Invalid imported identity length')
                key = bytearray(memoryview(imported)[:1632])
            public = validate_key(key)
            random_secret = bytearray(os.urandom(32))
            state = encode_state(random_secret)
            for name, data in ((KEY_NAME, key), (STATE_NAMES[0], state), (STATE_NAMES[1], state)):
                handle = targets[name]
                if handle.write(data) != len(data):
                    raise OSError('Short private-material write')
                handle.flush()
                os.fsync(handle.fileno())
                handle.seek(0)
                readback = bytearray(len(data) + 1)
                if handle.readinto(readback) != len(data) or not hmac.compare_digest(memoryview(readback)[:len(data)], data):
                    raise ValueError('Private-material readback failed')
                erase(readback)
                private_acl(private / name)
            private_acl(private)
        public_directory = output / 'public'
        public_directory.mkdir(mode=0o755)
        pin = hashlib.sha256(public).hexdigest()
        write_new(public_directory / 'public.bin', public)
        write_new(public_directory / 'public.sha256', (pin + '\n').encode('ascii'))
        record = {
            'status': 'SD_IDENTITY_PREPARED', 'profile': 'sd-persistent-state',
            'identity_source': 'explicit-existing-key' if source is not None else 'new-key',
            'public_key_sha256': pin, 'initial_generation': 0,
            'private_key_bytes': 1632, 'state_file_bytes': 80,
            'private_files': [KEY_NAME, *STATE_NAMES],
            'trusted_initial_preparation_required': True,
            'preparation_pc_knew_private_material': True,
            'host_seed_injection_required': False,
            'sd_readout_protected': False, 'snapshot_rollback_protected': False,
            'hardware_entropy_source': False, 'production_security_accepted': False,
            'user_acceptance': 'pending', 'board_accessed': False, 'sd_card_written': False,
        }
        write_new(output / 'identity.json', (json.dumps(record, indent=2) + '\n').encode('utf-8'))
        return record
    finally:
        # Python/reference-KEM/OS immutable or native copies cannot be guaranteed erased.
        for value in (seed, key, imported, random_secret, state, readback):
            erase(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New absolute local directory')
    parser.add_argument('--identity-file', type=Path,
                        help='Explicit protected existing 1632-byte identity to preserve its public pin')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(args.output, args.identity_file), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, TypeError):
        print('SD_IDENTITY_ERROR: preparation failed; do not deploy partial files or overwrite the output', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
