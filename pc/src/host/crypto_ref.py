"""Offline golden models. Deterministic ML-KEM seeds are TEST DATA ONLY."""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from kyber_py.ml_kem import ML_KEM_512

MAX_AAD = 64
MAX_PLAINTEXT = 1400


def _check(key, nonce, aad, length):
    if len(key) != 16 or len(nonce) != 12:
        raise ValueError("AES-128 key / 96-bit nonce required")
    if len(aad) > MAX_AAD or not 0 <= length <= MAX_PLAINTEXT:
        raise ValueError("AAD or payload exceeds v1 limits")


def encrypt(key, nonce, plaintext, aad=b""):
    _check(key, nonce, aad, len(plaintext))
    sealed = AESGCM(key).encrypt(nonce, plaintext, aad)
    return sealed[:-16], sealed[-16:]


def decrypt(key, nonce, ciphertext, tag, aad=b""):
    _check(key, nonce, aad, len(ciphertext))
    if len(tag) != 16:
        raise ValueError("128-bit tag required")
    # AESGCM releases no plaintext if authentication fails (InvalidTag).
    return AESGCM(key).decrypt(nonce, ciphertext + tag, aad)


def aes_block(key, block):
    if len(key) != 16 or len(block) != 16:
        raise ValueError("AES-128 block/key must be 16 bytes")
    ctx = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return ctx.update(block) + ctx.finalize()


def gf128_mul(x, y):
    """SP 800-38D Algorithm 1: MSB first, R = e1 || 0^120."""
    if not 0 <= x < 1 << 128 or not 0 <= y < 1 << 128:
        raise ValueError("GF operands must be 128-bit unsigned values")
    result = 0
    for bit in range(127, -1, -1):
        if (x >> bit) & 1:
            result ^= y
        y = (y >> 1) ^ ((0xe1 << 120) if y & 1 else 0)
    return result


def ghash_trace(key, nonce, aad, ciphertext):
    _check(key, nonce, aad, len(ciphertext))
    h = aes_block(key, bytes(16))
    j0 = nonce + b"\x00\x00\x00\x01"
    blocks = []
    for data in (aad, ciphertext):
        blocks.extend(data[i:i + 16].ljust(16, b"\x00")
                      for i in range(0, len(data), 16))
    blocks.append((len(aad) * 8).to_bytes(8, "big") +
                  (len(ciphertext) * 8).to_bytes(8, "big"))
    state = 0
    states = []
    for block in blocks:
        state = gf128_mul(state ^ int.from_bytes(block, "big"), int.from_bytes(h, "big"))
        states.append(state.to_bytes(16, "big").hex())
    mask = int.from_bytes(aes_block(key, j0), "big")
    return {"h": h.hex(), "j0": j0.hex(), "blocks": [b.hex() for b in blocks],
            "states": states, "tag": (state ^ mask).to_bytes(16, "big").hex()}


def mlkem_vector(seed, message):
    """FIPS 203 internal deterministic entry points, only for offline KATs.

    kyber-py==1.2.0 is an educational, non-constant-time reference. The
    pinned private encaps API exposes m for ACVP; never use this for sessions.
    """
    if len(seed) != 64 or len(message) != 32:
        raise ValueError("ML-KEM test seed/message must be 64/32 bytes")
    ek, dk = ML_KEM_512.key_derive(seed)
    secret, ciphertext = ML_KEM_512._encaps_internal(ek, message)
    if ML_KEM_512.decaps(dk, ciphertext) != secret:
        raise RuntimeError("ML-KEM golden reference roundtrip failed")
    return {"seed": seed.hex(), "m": message.hex(), "ek": ek.hex(), "dk": dk.hex(),
            "c": ciphertext.hex(), "k": secret.hex()}
