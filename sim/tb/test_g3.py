"""Small host-side check for G3 chunk framing and authenticated reassembly."""
from pathlib import Path
import struct
import sys

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/host"))
from g3_board import CHUNK, verify

key, prefix = bytes(range(16)), bytes(range(8))
for n in (4, 1399, 1400, 1401, 2801, 65536):
    nonce_start = 77 if n == 2801 else 0
    frame = b"\xff\xd8" + bytes((i * 17) & 255 for i in range(n - 4)) + b"\xff\xd9"
    chunks = (n + CHUNK - 1) // CHUNK
    packets = bytearray()
    for index in range(chunks):
        offset = index * CHUNK
        aad = struct.pack(">4I", n, offset, index, chunks)
        nonce = prefix + (nonce_start + index).to_bytes(4, "big")
        packets.extend(AESGCM(key).encrypt(nonce, frame[offset:offset + CHUNK], aad))
    assert verify(frame, packets, key, prefix, nonce_start) == chunks
    packets[-1] ^= 1
    try:
        verify(frame, packets, key, prefix, nonce_start)
    except InvalidTag:
        pass
    else:
        raise AssertionError("G3 accepted a modified Tag")
print("G3_HOST_PASS lengths=6 tamper=6")
