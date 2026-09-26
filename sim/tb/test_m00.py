"""Run with: .venv/Scripts/python.exe sim/tb/test_m00.py (C compiler required)."""

import ctypes as ct
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import random
import shlex
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src" / "host"), str(ROOT / "sim" / "scripts")]
import protocol as p
from crypto_ref import encrypt, decrypt, ghash_trace, aes_block, mlkem_vector, ML_KEM_512
from cryptography.exceptions import InvalidTag
from generate_vectors import encoded_files


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class CHeader(ct.Structure):
    _fields_ = [(name, ctype) for name, ctype in (
        ("version", ct.c_uint8), ("flags", ct.c_uint8), ("header_length", ct.c_uint16),
        ("session_id", ct.c_uint32), ("frame_id", ct.c_uint32),
        ("packet_id", ct.c_uint16), ("packet_count", ct.c_uint16),
        ("jpeg_length", ct.c_uint32), ("payload_length", ct.c_uint16),
        ("reserved", ct.c_uint16), ("timestamp", ct.c_uint64), ("packet_sequence", ct.c_uint64))]


class M00(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gcm = load("sim/vectors/aes_gcm.json")["vectors"]
        cls.temp = tempfile.TemporaryDirectory(prefix="eyepqc-m00-")
        library = Path(cls.temp.name) / ("protocol.dll" if os.name == "nt" else "protocol.so")
        compiler = shlex.split(os.environ.get("CC", "gcc"), posix=os.name != "nt")
        subprocess.run(compiler + ["-std=c99", "-Wall", "-Wextra", "-Werror", "-pedantic",
                                   "-shared", "-fPIC", "-I", str(ROOT / "src/ps/include"),
                                   str(ROOT / "src/ps/src/protocol.c"), "-o", str(library)], check=True)
        cls.lib = ct.CDLL(str(library))
        ptr, size = ct.c_void_p, ct.c_size_t
        cls.lib.eye_video_encode.argtypes = [ptr, size, ct.POINTER(CHeader)]
        cls.lib.eye_video_decode.argtypes = [ct.POINTER(CHeader), ptr, size]
        cls.lib.eye_video_validate.argtypes = [ct.POINTER(CHeader)]
        cls.lib.eye_datagram_validate.argtypes = [ct.POINTER(CHeader), size, ct.c_int]
        cls.lib.eye_nonce_encode.argtypes = [ptr, size, ct.c_uint32, ct.c_uint64]
        cls.lib.eye_control_encode.argtypes = [ptr, size, ct.c_uint8, ptr, size]
        cls.lib.eye_control_prefix.argtypes = [ptr, ptr, ptr, size]
        cls.lib.eye_control_decode.argtypes = [ptr, ptr, ptr, ptr, size]

    @classmethod
    def tearDownClass(cls):
        # Unload before removing the temporary library (Windows locks loaded DLLs).
        if os.name == "nt":
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        del cls.lib
        cls.temp.cleanup()

    def test_nist_aes_and_gcm(self):
        self.assertEqual(aes_block(bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
                                   bytes.fromhex("00112233445566778899aabbccddeeff")).hex(),
                         "69c4e0d86a7b0430d8cdb78070b4c55a")
        vectors = load("data/kat/nist_gcm.json")["vectors"]
        self.assertEqual(len(vectors), 20)
        for v in vectors:
            key, nonce, aad, plaintext, ciphertext, tag = (
                bytes.fromhex(v[f]) for f in ("key", "nonce", "aad", "plaintext", "ciphertext", "tag"))
            self.assertEqual(encrypt(key, nonce, plaintext, aad), (ciphertext, tag))
            self.assertEqual(decrypt(key, nonce, ciphertext, tag, aad), plaintext)
            self.assertEqual(ghash_trace(key, nonce, aad, ciphertext)["tag"], tag.hex())

    def test_boundaries_and_random(self):
        for v in self.gcm:
            key, nonce, aad, plaintext, ciphertext, tag = (
                bytes.fromhex(v[f]) for f in ("key", "nonce", "aad", "plaintext", "ciphertext", "tag"))
            self.assertEqual(encrypt(key, nonce, plaintext, aad), (ciphertext, tag), v["name"])
            self.assertEqual(decrypt(key, nonce, ciphertext, tag, aad), plaintext)
            self.assertEqual(ghash_trace(key, nonce, aad, ciphertext), v["ghash"])
        lengths = {len(bytes.fromhex(v["plaintext"])) for v in self.gcm if v["name"].startswith("boundary")}
        self.assertEqual(lengths, {0, 1, 15, 16, 17, 31, 32, 1400})

    def test_tamper_and_every_bit(self):
        lookup = {v["name"]: v for v in self.gcm}
        for t in load("sim/vectors/aes_gcm_tamper.json")["vectors"]:
            v = dict(lookup[t["base"]], **{t["field"]: t["replacement"]})
            with self.assertRaises(InvalidTag):
                decrypt(*(bytes.fromhex(v[f]) for f in ("key", "nonce", "ciphertext", "tag", "aad")))
        v = lookup["boundary_17_aad_40"]
        for field in ("key", "nonce", "aad", "ciphertext", "tag"):
            original = bytes.fromhex(v[field])
            for bit in range(len(original) * 8):
                raw = bytearray(original)
                raw[bit // 8] ^= 1 << (bit % 8)
                changed = dict(v, **{field: raw.hex()})
                with self.assertRaises(InvalidTag):
                    decrypt(*(bytes.fromhex(changed[f]) for f in ("key", "nonce", "ciphertext", "tag", "aad")))

    def test_crypto_limits(self):
        for key, nonce, plaintext, aad in ((bytes(15), bytes(12), b"", b""),
                                          (bytes(16), bytes(13), b"", b""),
                                          (bytes(16), bytes(12), bytes(1401), b""),
                                          (bytes(16), bytes(12), b"", bytes(65))):
            with self.assertRaises(ValueError):
                encrypt(key, nonce, plaintext, aad)
        with self.assertRaises(ValueError):
            decrypt(bytes(16), bytes(12), b"", bytes(15))

    def test_mlkem_acvp(self):
        data = load("data/kat/nist_mlkem512.json")
        self.assertEqual(tuple(len(data[k]) for k in ("keygen", "encapsulation", "decapsulation")),
                         (25, 25, 10))
        for v in data["keygen"]:
            seed = bytes.fromhex(v["d"] + v["z"])
            ek, dk = ML_KEM_512.key_derive(seed)
            self.assertEqual(ek.hex(), v["ek"].lower())
            self.assertEqual(dk.hex(), v["dk"].lower())
        for v in data["encapsulation"]:
            k, c = ML_KEM_512._encaps_internal(bytes.fromhex(v["ek"]), bytes.fromhex(v["m"]))
            self.assertEqual(k.hex(), v["k"].lower())
            self.assertEqual(c.hex(), v["c"].lower())
            self.assertEqual(ML_KEM_512.decaps(bytes.fromhex(v["dk"]), c), k)
        for v in data["decapsulation"]:
            k = ML_KEM_512.decaps(bytes.fromhex(v["dk"]), bytes.fromhex(v["c"]))
            self.assertEqual(k.hex(), v["k"].lower())
        for v in load("sim/vectors/mlkem512.json")["vectors"]:
            self.assertEqual(mlkem_vector(bytes.fromhex(v["seed"]), bytes.fromhex(v["m"])), v)
            c = bytearray.fromhex(v["c"])
            c[0] ^= 1
            self.assertNotEqual(ML_KEM_512.decaps(bytes.fromhex(v["dk"]), bytes(c)).hex(), v["k"])
            with self.assertRaises(ValueError):
                ML_KEM_512.decaps(bytes.fromhex(v["dk"]), bytes(c[:-1]))

    def test_reproducibility(self):
        first, second = encoded_files(), encoded_files()
        self.assertEqual(first, second)
        manifest = load("sim/vectors/sha256.json")
        for name, data in first.items():
            self.assertEqual((ROOT / "sim/vectors" / name).read_bytes(), data)
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest[name])
        for name, expected in load("data/kat/sources.json")["files"].items():
            self.assertEqual(hashlib.sha256((ROOT / "data/kat" / name).read_bytes()).hexdigest(), expected)

    def test_python_c_video_interop(self):
        rng = random.Random(203)
        for index in range(1000):
            length = rng.randint(4, p.MAX_JPEG)
            count = (length + 1399) // 1400
            h = p.packet_header(rng.getrandbits(32), rng.getrandbits(32), length,
                                rng.randrange(count), rng.getrandbits(64), rng.getrandbits(64),
                                encrypted=bool(index % 2))
            c = CHeader(*(getattr(h, name) for name, _ in CHeader._fields_))
            buf = ct.create_string_buffer(41)
            self.assertEqual(self.lib.eye_video_encode(ct.byref(buf, 1), 40, ct.byref(c)), 0)
            self.assertEqual(buf.raw[1:], h.pack())
            decoded = CHeader()
            self.assertEqual(self.lib.eye_video_decode(ct.byref(decoded), ct.byref(buf, 1), 40), 0)
            self.assertEqual([getattr(decoded, n) for n, _ in CHeader._fields_],
                             [getattr(h, n) for n, _ in CHeader._fields_])
            self.assertEqual(p.VideoHeader.unpack(buf.raw[1:]), h)
        nonce = ct.create_string_buffer(12)
        self.assertEqual(self.lib.eye_nonce_encode(nonce, 12, 0x11223344, 0x0102030405060708), 0)
        self.assertEqual(nonce.raw.hex(), "112233440102030405060708")
        self.assertEqual(nonce.raw, p.make_nonce(0x11223344, 0x0102030405060708))

    def test_video_validation(self):
        h = p.packet_header(1, 2, 1401, 1, 3, 4)
        c = CHeader(*(getattr(h, name) for name, _ in CHeader._fields_))
        canary = ct.create_string_buffer(b"x" * 40, 40)
        self.assertNotEqual(self.lib.eye_video_encode(canary, 39, ct.byref(c)), 0)
        self.assertEqual(canary.raw, b"x" * 40)
        self.assertNotEqual(self.lib.eye_video_decode(ct.byref(c), h.pack(), 39), 0)
        for change in ({"version": 2}, {"flags": 2}, {"header_length": 39}, {"reserved": 1},
                       {"jpeg_length": 3}, {"jpeg_length": p.MAX_JPEG + 1},
                       {"packet_id": 2}, {"packet_count": 1}, {"payload_length": 0},
                       {"payload_length": 2}):
            bad = replace(h, **change)
            with self.assertRaises(ValueError):
                bad.pack()
            c = CHeader(*(getattr(bad, name) for name, _ in CHeader._fields_))
            self.assertNotEqual(self.lib.eye_video_validate(ct.byref(c)), 0)
        for field in ("session_id", "frame_id", "timestamp", "packet_sequence"):
            with self.assertRaises(ValueError):
                replace(h, **{field: -1}).pack()
        for packet in load("sim/vectors/protocol.json")["packets"]:
            wire = bytes.fromhex(packet["datagram"])
            header, aad, ciphertext, tag = p.decode_video(wire)
            self.assertEqual(decrypt(bytes.fromhex(packet["key"]), bytes.fromhex(packet["nonce"]),
                                     ciphertext, tag, aad).hex(), packet["plaintext"])
            self.assertEqual(p.encode_video(header, ciphertext, tag), wire)
            c = CHeader(*(getattr(header, name) for name, _ in CHeader._fields_))
            self.assertEqual(self.lib.eye_datagram_validate(ct.byref(c), len(wire), 0), 0)
            self.assertNotEqual(self.lib.eye_datagram_validate(ct.byref(c), len(wire) - 1, 0), 0)
            for truncated in (wire[:39], wire[:-1], wire + b"\x00"):
                with self.assertRaises(ValueError):
                    p.decode_video(truncated)
        plain = p.encode_video(replace(h, flags=0), b"x")
        with self.assertRaises(ValueError):
            p.decode_video(plain)
        self.assertEqual(p.decode_video(plain, allow_plaintext=True)[2], b"x")
        c = CHeader(*(getattr(replace(h, flags=0), name) for name, _ in CHeader._fields_))
        self.assertNotEqual(self.lib.eye_datagram_validate(ct.byref(c), len(plain), 0), 0)
        self.assertEqual(self.lib.eye_datagram_validate(ct.byref(c), len(plain), 1), 0)

    def test_control_stream_and_c_interop(self):
        hello = struct.pack("!BBH", 1, 1, 1) + bytes(range(32))
        messages = [(kind, hello if kind in (1, 2) else
                     b"\x00\x01" + "测试".encode() if kind == 9 else bytes(p.CONTROL_LENGTHS[kind]))
                    for kind in p.MessageType]
        wire = b"".join(p.encode_control(kind, body) for kind, body in messages)
        for chunk in (1, 3, 12, 13, 47, 768, len(wire)):
            decoder = p.ControlDecoder()
            actual = []
            for start in range(0, len(wire), chunk):
                actual.extend(decoder.feed(wire[start:start + chunk]))
                self.assertLessEqual(len(decoder.buffer), p.MAX_CONTROL + 12)
            decoder.finish()
            self.assertEqual(actual, messages)
        for kind, body in messages:
            packed = p.encode_control(kind, body)
            output = ct.create_string_buffer(len(packed))
            self.assertEqual(self.lib.eye_control_encode(output, len(packed), kind, body, len(body)), 0)
            self.assertEqual(output.raw, packed)
            ctype, size, ptr = ct.c_uint8(), ct.c_uint32(), ct.c_void_p()
            self.assertEqual(self.lib.eye_control_decode(ct.byref(ctype), ct.byref(ptr),
                                                         ct.byref(size), output, len(packed)), 0)
            self.assertEqual((ctype.value, ct.string_at(ptr, size.value)), (kind, body))

    def test_control_rejects_unsafe_inputs(self):
        invalid = [p.CONTROL_HEADER.pack(b"EYPQ", 1, 1, 0, 2**32 - 1),
                   p.CONTROL_HEADER.pack(b"EYPQ", 1, 10, 0, 0),
                   p.CONTROL_HEADER.pack(b"EYPQ", 1, 1, 1, 36),
                   p.CONTROL_HEADER.pack(b"EYPQ", 2, 1, 0, 36),
                   p.CONTROL_HEADER.pack(b"NOPE", 1, 1, 0, 36)]
        for prefix in invalid:
            decoder = p.ControlDecoder()
            with self.assertRaises(ValueError):
                decoder.feed(prefix)
            self.assertEqual(len(decoder.buffer), 0)
            kind, size = ct.c_uint8(), ct.c_uint32()
            self.assertNotEqual(self.lib.eye_control_prefix(ct.byref(kind), ct.byref(size), prefix, 12), 0)
        for body in (b"\x00\x00", b"\x00\x08", b"\x00\x01\xff",
                     b"\x00\x01\xc0\x80", b"\x00\x01\xed\xa0\x80", b"\x00\x01\xf4\x90\x80\x80"):
            with self.assertRaises(ValueError):
                p.encode_control(9, body)
            output = ct.create_string_buffer(300)
            self.assertNotEqual(self.lib.eye_control_encode(output, 300, 9, body, len(body)), 0)
        decoder = p.ControlDecoder()
        decoder.feed(b"EYPQ")
        with self.assertRaises(ValueError):
            decoder.finish()


if __name__ == "__main__":
    unittest.main(verbosity=2)
