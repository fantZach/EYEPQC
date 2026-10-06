"""M08 full RTL AXI-Lite/AXIS against stored M00 and NIST AES-GCM vectors."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from iverilog_runner import compile_iverilog

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / "src/rtl/crypto"


def tool(name):
    found = shutil.which(name)
    if found:
        return found
    windows = Path(f"C:/iverilog/bin/{name}.exe")
    if os.name == "nt" and windows.is_file():
        return str(windows)
    raise RuntimeError(f"Install {name} or add it to PATH")


class M08(unittest.TestCase):
    def test_full_axis_gcm(self):
        vectors = json.loads((ROOT / "sim/vectors/aes_gcm.json").read_text())["vectors"]
        vectors += json.loads((ROOT / "data/kat/nist_gcm.json").read_text())["vectors"]
        self.assertEqual(len(vectors), 100)
        previous_key = bytes.fromhex(vectors[-1]["key"])
        reload_nonce = bytes.fromhex("f1" * 12)
        for key in (previous_key, bytes(range(16))):
            aad, plain = b"hdr", b"consecutive-packet"
            sealed = AESGCM(key).encrypt(reload_nonce, plain, aad)
            vectors.append(dict(key=key.hex(), nonce=reload_nonce.hex(), aad=aad.hex(),
                                plaintext=plain.hex(), ciphertext=sealed[:-16].hex(),
                                tag=sealed[-16:].hex()))
        lines = [str(len(vectors))]
        for item in vectors:
            key, nonce, aad, plain, cipher, tag = (
                bytes.fromhex(item[name]) for name in
                ("key", "nonce", "aad", "plaintext", "ciphertext", "tag")
            )
            self.assertEqual(AESGCM(key).encrypt(nonce, plain, aad), cipher + tag)
            self.assertEqual(AESGCM(key).decrypt(nonce, cipher + tag, aad), plain)
            for changed_key, changed_nonce, changed_aad in (
                (bytes([key[0] ^ 1]) + key[1:], nonce, aad),
                (key, bytes([nonce[0] ^ 1]) + nonce[1:], aad),
                (key, nonce, bytes([aad[0] ^ 1]) + aad[1:] if aad else b"\x01"),
            ):
                with self.assertRaises(InvalidTag):
                    AESGCM(changed_key).decrypt(changed_nonce, cipher + tag, changed_aad)
            if cipher:
                damaged = bytes([cipher[0] ^ 1]) + cipher[1:] + tag
                with self.assertRaises(InvalidTag):
                    AESGCM(key).decrypt(nonce, damaged, aad)
            with self.assertRaises(InvalidTag):
                AESGCM(key).decrypt(nonce, cipher + tag[:-1] + bytes([tag[-1] ^ 1]), aad)
            lines.append(f"{key.hex()} {nonce.hex()} {len(aad)} {len(plain)} "
                         f"{aad.ljust(64, bytes(1)).hex()} "
                         f"{plain.ljust(1400, bytes(1)).hex()} "
                         f"{cipher.ljust(1400, bytes(1)).hex()} {tag.hex()}")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            input_file = work / "gcm_vectors.txt"
            input_file.write_text("\n".join(lines) + "\n")
            sources = [RTL / "secworks_aes" / name for name in (
                "aes_core.v", "aes_key_mem.v", "aes_encipher_block.v",
                "aes_decipher_block.v", "aes_sbox.v", "aes_inv_sbox.v")]
            sources += [ROOT / "src/rtl/common/axis_byte_packer.sv"]
            sources += [RTL / name for name in (
                "gf128_mul.sv", "ghash.sv", "aes_gcm_encrypt.sv",
                "aes_gcm_regs.sv", "aes_gcm_axis.sv")]
            sources += [ROOT / "sim/tb/tb_aes_gcm_axis.sv"]
            executable = work / "m08.vvp"
            compile_iverilog([tool("iverilog"), "-g2012", "-s", "tb_aes_gcm_axis",
                              "-o", str(executable), *map(str, sources)], executable)
            result = subprocess.run([tool("vvp"), str(executable),
                                     f"+VECTORS={input_file}"], cwd=ROOT,
                                    capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("AES_GCM_AXIS_PASS cases=102", result.stdout)
            print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
