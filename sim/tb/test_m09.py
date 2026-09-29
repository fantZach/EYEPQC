"""Run: python sim/tb/test_m09.py (requires a C compiler)."""
import ctypes as ct
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/host"))
from m09 import Kem, build


def main():
    vectors = json.loads((ROOT / "data/kat/nist_mlkem512.json").read_text())
    with tempfile.TemporaryDirectory(prefix="eyepqc-m09-") as temp:
        lib = build(Path(temp) / "mlkem.dll")
        kem = Kem(lib)
        for vector in vectors["keygen"]:
            pk, sk = kem.keygen(bytes.fromhex(vector["d"] + vector["z"]))
            assert pk.hex() == vector["ek"].lower()
            assert sk.hex() == vector["dk"].lower()
        for vector in vectors["encapsulation"]:
            ciphertext, shared = kem.encaps(bytes.fromhex(vector["ek"]),
                                             bytes.fromhex(vector["m"]))
            assert ciphertext.hex() == vector["c"].lower()
            assert shared.hex() == vector["k"].lower()
            assert kem.decaps(bytes.fromhex(vector["dk"]), ciphertext) == shared
        for vector in vectors["decapsulation"]:
            assert kem.decaps(bytes.fromhex(vector["dk"]), bytes.fromhex(vector["c"])).hex() == vector["k"].lower()
        vector = vectors["encapsulation"][0]
        sk, ciphertext = bytes.fromhex(vector["dk"]), bytes.fromhex(vector["c"])
        expected = bytes.fromhex(vector["k"])
        for _ in range(1000):
            assert kem.decaps(sk, ciphertext) == expected
        changed = bytearray(ciphertext)
        changed[0] ^= 1
        assert kem.decaps(sk, changed) != expected
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
