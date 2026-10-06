"""Prepare local development ML-KEM material; no board/USB access or key output."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/host'))
from m09 import OUT, LIB, PK, SK, Kem, build


def main():
    paths = [OUT / name for name in ('public.bin', 'private.bin', 'public.sha256')]
    if any(p.exists() for p in paths) and not all(p.is_file() for p in paths):
        raise RuntimeError('Incomplete development key files; refusing to overwrite')
    build(LIB)
    kem = Kem()
    if not any(p.exists() for p in paths):
        pk, sk = kem.keygen(secrets.token_bytes(64))
        paths[0].write_bytes(pk)
        paths[1].write_bytes(sk)
        paths[2].write_text(hashlib.sha256(pk).hexdigest() + '\n', encoding='ascii')
    pk, sk = paths[0].read_bytes(), paths[1].read_bytes()
    if (len(pk), len(sk)) != (PK, SK) or sk[768:1568] != pk:
        raise RuntimeError('Development key mismatch')
    if hashlib.sha256(pk).hexdigest() != paths[2].read_text().strip():
        raise RuntimeError('Development public-key pin mismatch')
    ciphertext, shared = kem.encaps(pk, secrets.token_bytes(32))
    if kem.decaps(sk, ciphertext) != shared:
        raise RuntimeError('Development ML-KEM roundtrip failed')
    (OUT / 'preparation.json').write_text(json.dumps(dict(status='PASS',
        library_sha256=hashlib.sha256(LIB.read_bytes()).hexdigest(),
        development_only=True, board_accessed=False), indent=2) + '\n', encoding='utf-8')
    if os.name == 'nt':
        import _ctypes
        _ctypes.FreeLibrary(kem.lib._handle)
    print('DEMO_PREPARED development_only=true board_accessed=false')


if __name__ == '__main__':
    main()
