"""Explicit offline creation of one protected, PC-trusted development identity."""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys

from kyber_py.ml_kem import ML_KEM_512

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pc/src/host'))
from private_acl import private_acl


def erase(value):
    if value is not None:
        value[:] = b'\0' * len(value)


def write_new(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, 'wb') as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())


def create_identity(output):
    output = Path(output)
    if not output.is_absolute() or str(output).startswith(('\\\\', '//')):
        raise ValueError('Use a new absolute local directory')
    for part in (output, *output.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('Identity paths must not traverse links')
    if output.exists():
        raise FileExistsError('Never overwrite an existing identity directory')
    if not output.parent.is_dir():
        raise ValueError('Identity parent directory must already exist')
    output.mkdir(mode=0o700)
    private = output / 'private'
    private.mkdir(mode=0o700)
    private_acl(private, protect=True)
    identity = private / 'board-test-identity.bin'
    # Verify the inherited file ACL before generating or writing any secret.
    descriptor = os.open(identity, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    seed = secret = stored = None
    try:
        with os.fdopen(descriptor, 'w+b') as target:
            private_acl(identity)
            seed = bytearray(os.urandom(64))
            public, immutable_secret = ML_KEM_512.key_derive(bytes(seed))
            secret = bytearray(immutable_secret)
            immutable_secret = None
            if (len(public) != 800 or len(secret) != 1632 or
                    not hmac.compare_digest(memoryview(secret)[768:1568], public) or
                    not hmac.compare_digest(memoryview(secret)[1568:1600], hashlib.sha3_256(public).digest())):
                raise ValueError('Invalid ML-KEM-512 development key pair')
            target.write(secret)
            target.flush()
            os.fsync(target.fileno())
            target.seek(0)
            stored = bytearray(1633)
            if target.readinto(stored) != 1632 or not hmac.compare_digest(memoryview(stored)[:1632], secret):
                raise ValueError('Development identity readback failed')
            private_acl(private)
            private_acl(identity)
        public_directory = output / 'public'
        public_directory.mkdir(mode=0o755)
        pin = hashlib.sha256(public).hexdigest()
        write_new(public_directory / 'public.bin', public)
        write_new(public_directory / 'public.sha256', (pin + '\n').encode('ascii'))
        record = {'status': 'DEVELOPMENT_IDENTITY_CREATED', 'development_only': True,
                  'trusted_pc_required': True, 'production_security_accepted': False,
                  'user_acceptance': 'pending', 'public_key_sha256': pin,
                  'private_key_bytes': 1632, 'public_key_bytes': 800,
                  'keygen_seed_file_created': False, 'board_accessed': False}
        write_new(output / 'identity.json', (json.dumps(record, indent=2) + '\n').encode('utf-8'))
        return record
    finally:
        # Owned buffers only: the reference Python KEM and OS may retain immutable/native copies.
        erase(seed)
        erase(secret)
        erase(stored)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='New absolute local directory; never reuse or overwrite an identity')
    args = parser.parse_args(argv)
    try:
        print(json.dumps(create_identity(args.output), indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, TypeError):
        print('DEV_IDENTITY_ERROR: creation failed or output exists; inspect the new directory locally, do not overwrite',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
