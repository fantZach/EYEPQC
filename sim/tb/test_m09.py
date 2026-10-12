"""Run: python sim/tb/test_m09.py (requires a C compiler)."""
import ctypes as ct
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc/src/host"))
from m09 import Kem, build
from handshake import wipe_secret


def main():
    vectors = json.loads((ROOT / "data/kat/nist_mlkem512.json").read_text())
    with tempfile.TemporaryDirectory(prefix="eyepqc-m09-") as temp:
        lib = build(Path(temp) / "mlkem.dll")
        kem = Kem(lib)
        for vector in vectors["keygen"]:
            pk, sk = kem.keygen(bytes.fromhex(vector["d"] + vector["z"]))
            try:
                assert pk.hex() == vector["ek"].lower()
                assert sk.hex() == vector["dk"].lower()
            finally:
                wipe_secret(sk)
        for vector in vectors["encapsulation"]:
            ciphertext, shared = kem.encaps(bytes.fromhex(vector["ek"]),
                                             bytes.fromhex(vector["m"]))
            decapsulated = None
            try:
                assert ciphertext.hex() == vector["c"].lower()
                assert shared.hex() == vector["k"].lower()
                decapsulated = kem.decaps(bytes.fromhex(vector["dk"]), ciphertext)
                assert decapsulated == shared
            finally:
                wipe_secret(shared)
                wipe_secret(decapsulated)
        for vector in vectors["decapsulation"]:
            shared = kem.decaps(bytes.fromhex(vector["dk"]), bytes.fromhex(vector["c"]))
            try:
                assert shared.hex() == vector["k"].lower()
            finally:
                wipe_secret(shared)
        vector = vectors["encapsulation"][0]
        sk, ciphertext = bytes.fromhex(vector["dk"]), bytes.fromhex(vector["c"])
        expected = bytes.fromhex(vector["k"])
        for _ in range(1000):
            shared = kem.decaps(sk, ciphertext)
            try:
                assert shared == expected
            finally:
                wipe_secret(shared)
        changed = bytearray(ciphertext)
        changed[0] ^= 1
        shared = kem.decaps(sk, changed)
        try:
            assert shared != expected
        finally:
            wipe_secret(shared)
        for secret, encrypted in ((sk[:-1], ciphertext), (sk, ciphertext[:-1])):
            try:
                kem.decaps(secret, encrypted)
            except ValueError:
                pass
            else:
                raise AssertionError("malformed length accepted")
        corrupt = bytearray(sk)
        corrupt[1568] ^= 1  # Stored H(pk), checked by Decaps.
        try:
            kem.decaps(corrupt, ciphertext)
        except ValueError:
            pass
        else:
            raise AssertionError("corrupt secret key accepted")
        print("M09 PC PASS: ACVP 25 keygen + 25 encaps + 10 decaps; 1000 repeats; tamper/length")
        # ctypes keeps a DLL loaded on Windows. Explicitly unload before temp cleanup.
        if sys.platform == "win32":
            import _ctypes
            _ctypes.FreeLibrary(kem.lib._handle)
        del kem


if __name__ == "__main__":
    main()
