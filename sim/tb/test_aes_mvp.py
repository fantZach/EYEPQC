"""Actual vendored AES/AXI RTL + portable C GCM vs existing golden references."""
import ctypes
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/host"))
from crypto_ref import aes_block
from aes_image_mvp import LIMIT, JOB_SIZE, demo_png, pack_job, verify_reply


def tool(name, windows):
    found = shutil.which(name)
    if found: return found
    if os.name == "nt" and Path(windows).is_file(): return windows
    raise RuntimeError(f"Install {name} or add it to PATH")


class AesMvp(unittest.TestCase):
    def test_image_mailbox_authentication(self):
        image, key, nonce = demo_png(), bytes(range(16)), bytes(range(12))
        request, aad = pack_job(image, key, nonce)
        sealed = AESGCM(key).encrypt(nonce, image, aad)
        reply = bytearray(request)
        reply[4:8] = (2).to_bytes(4, 'little')
        reply[16:44] = bytes(28)
        reply[60:60 + len(image)] = sealed[:-16]
        reply[-16:] = sealed[-16:]
        self.assertEqual(verify_reply(bytes(reply), image, key, nonce, aad)[2], image)
        for offset in (0, 4, 8, 12, 16, 44, 60, len(reply) - 1):
            changed = bytearray(reply); changed[offset] ^= 1
            with self.assertRaises((ValueError, InvalidTag)):
                verify_reply(bytes(changed), image, key, nonce, aad)
        self.assertEqual(len(request), JOB_SIZE)
        self.assertEqual(len(pack_job(bytes(LIMIT), key, nonce)[0]), JOB_SIZE)
        with self.assertRaises(ValueError): pack_job(bytes(LIMIT + 1), key, nonce)
        with self.assertRaises(ValueError): verify_reply(bytes(reply[:-1]), image, key, nonce, aad)

    def test_actual_aes_axi_rtl(self):
        vectors = [(bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
                    bytes.fromhex("00112233445566778899aabbccddeeff"))]
        for i in range(12):
            raw = hashlib.shake_256(f"AES MVP test {i}".encode()).digest(32)
            vectors.append((raw[:16], raw[16:]))
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            data = work / "blocks.txt"
            data.write_text("".join(f"{k.hex()} {b.hex()} {aes_block(k, b).hex()}\n" for k, b in vectors))
            rtl = sorted((ROOT / "src/rtl/crypto/secworks_aes").glob("*.v"))
            subprocess.run([tool("iverilog", "C:/iverilog/bin/iverilog.exe"), "-g2012",
                "-s", "tb_aes_axi_lite", "-o", str(work / "test.vvp"),
                str(ROOT / "src/rtl/crypto/aes_axi_lite.sv"),
                str(ROOT / "sim/tb/tb_aes_axi_lite.sv"), *map(str, rtl)], check=True)
            result = subprocess.run([tool("vvp", "C:/iverilog/bin/vvp.exe"),
                str(work / "test.vvp"), f"+VECTORS={data}"], check=True,
                text=True, capture_output=True, timeout=30)
            self.assertIn("AES_AXI_PASS vectors=13", result.stdout)

    def test_c_gcm_against_golden(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            library = Path(directory) / ("gcm.dll" if os.name == "nt" else "gcm.so")
            subprocess.run([tool("gcc", "C:/msys64/ucrt64/bin/gcc.exe"), "-shared", "-fPIC",
                "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "src/ps/include"),
                str(ROOT / "src/ps/src/mvp_gcm.c"), "-o", str(library)], check=True)
            lib = ctypes.CDLL(str(library))
            if os.name == "nt":
                cleanup.callback(ctypes.windll.kernel32.FreeLibrary, ctypes.c_void_p(lib._handle))
            byte = ctypes.c_uint8
            pointer = ctypes.POINTER(byte)
            callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, pointer, pointer)
            lib.mvp_gcm_encrypt.argtypes = [pointer, ctypes.c_size_t, pointer, pointer,
                ctypes.c_size_t, pointer, callback_type, ctypes.c_void_p]
            lib.mvp_gcm_encrypt.restype = ctypes.c_int
            vectors = json.loads((ROOT / "sim/vectors/aes_gcm.json").read_text())["vectors"]
            vectors += json.loads((ROOT / "data/kat/nist_gcm.json").read_text())["vectors"]
            for length in (4097, 65535, 65536, LIMIT - 1, LIMIT):
                plaintext = hashlib.shake_256(str(length).encode()).digest(length)
                key, nonce, aad = bytes(range(16)), bytes(range(12)), b"MVP image length"
                sealed = AESGCM(key).encrypt(nonce, plaintext, aad)
                vectors.append(dict(key=key.hex(), nonce=nonce.hex(), aad=aad.hex(),
                    plaintext=plaintext.hex(), ciphertext=sealed[:-16].hex(), tag=sealed[-16:].hex()))
            for vector in vectors:
                k, n, a, p, c, t = [bytes.fromhex(vector[field]) for field in
                    ("key", "nonce", "aad", "plaintext", "ciphertext", "tag")]
                def encrypt(_, source, dest):
                    ctypes.memmove(dest, aes_block(k, ctypes.string_at(source, 16)), 16)
                    return 0
                callback = callback_type(encrypt)
                payload = (byte * max(1, len(p)))(*p)
                iv, aad = (byte * 12)(*n), (byte * max(1, len(a)))(*a)
                tag = (byte * 16)()
                self.assertEqual(lib.mvp_gcm_encrypt(payload, len(p), iv, aad, len(a), tag, callback, None), 0)
                self.assertEqual(bytes(payload)[:len(p)], c)
                self.assertEqual(bytes(tag), t)
            failing = callback_type(lambda *_: 1)
            payload, tag = (byte * 17)(*range(17)), (byte * 16)(*range(16))
            self.assertEqual(lib.mvp_gcm_encrypt(payload, 17, iv, aad, len(a), tag, failing, None), 1)
            self.assertEqual(bytes(payload), bytes(17)); self.assertEqual(bytes(tag), bytes(16))
            calls = 0
            def fail_after_first_block(_, source, dest):
                nonlocal calls
                calls += 1
                if calls == 4: return 1
                ctypes.memmove(dest, aes_block(k, ctypes.string_at(source, 16)), 16)
                return 0
            payload, tag = (byte * 17)(*range(17)), (byte * 16)(*range(16))
            self.assertEqual(lib.mvp_gcm_encrypt(payload, 17, iv, aad, len(a), tag,
                             callback_type(fail_after_first_block), None), 1)
            self.assertEqual(calls, 4)
            self.assertEqual(bytes(payload), bytes(17)); self.assertEqual(bytes(tag), bytes(16))
            self.assertEqual(lib.mvp_gcm_encrypt(payload, LIMIT + 1, iv, aad, 0, tag, failing, None), 2)
            self.assertEqual(lib.mvp_gcm_encrypt(payload, 17, iv, aad, 65, tag, failing, None), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
