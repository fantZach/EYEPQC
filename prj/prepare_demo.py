"""Prepare local development ML-KEM material; no board/USB access or key output."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/host'))
from handshake import wipe_secret
from m09 import (OUT, LIB, SK, Kem, build, load_test_public_key,
                 write_test_key_material)
from transient_file import read_mutable_file


def main():
    build(LIB)
    kem = Kem()
    seed = generated_sk = sk = coins = shared = decaps_shared = None
    try:
        if not (OUT / 'private.bin').is_file():
            seed = bytearray(secrets.token_bytes(64))
            try:
                pk, generated_sk = kem.keygen(seed)
                write_test_key_material(OUT, pk, generated_sk)
            finally:
                wipe_secret(seed)
                wipe_secret(generated_sk)
        pk = load_test_public_key(OUT)
        sk = read_mutable_file(OUT / 'private.bin', SK)
        if len(sk) != SK or sk[768:1568] != pk:
            raise RuntimeError('Development key mismatch')
        coins = bytearray(secrets.token_bytes(32))
        ciphertext, shared = kem.encaps(pk, coins)
        decaps_shared = kem.decaps(sk, ciphertext)
        if not hmac.compare_digest(decaps_shared, shared):
            raise RuntimeError('Development ML-KEM roundtrip failed')
        (OUT / 'preparation.json').write_text(json.dumps(dict(status='PASS',
            library_sha256=hashlib.sha256(LIB.read_bytes()).hexdigest(),
            development_only=True, board_accessed=False), indent=2) + '\n', encoding='utf-8')
    finally:
        for secret in (seed, generated_sk, sk, coins, shared, decaps_shared):
            wipe_secret(secret)
        if os.name == 'nt':
            import _ctypes
            _ctypes.FreeLibrary(kem.lib._handle)
    print('DEMO_PREPARED development_only=true board_accessed=false')


if __name__ == '__main__':
    main()
