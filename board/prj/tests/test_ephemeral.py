"""Real portable C KeyGen/Decaps with independent Python MAC/HKDF checks."""
import ctypes as ct
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sim/tb"))
sys.path.insert(0, str(ROOT / "pc/src/host"))
from test_m10 import Session, array, setup
from m09 import Kem, build


class Ephemeral(ct.Structure):
    _fields_ = [("private_key", ct.c_ubyte * 1632), ("offer", ct.c_ubyte * 876), ("active", ct.c_ubyte)]


def record(kind, body):
    return b"EYPQ" + bytes([1, kind, 0, 0]) + len(body).to_bytes(4, "big") + body


def hkdf(shared, salt):
    prk = hmac.digest(salt, shared, "sha256")
    first = hmac.digest(prk, b"EYEPQC v1 keys\x01", "sha256")
    return (first + hmac.digest(prk, first + b"EYEPQC v1 keys\x02", "sha256"))[:56]


class EphemeralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.path = Path(cls.temp.name)
        library = cls.path / "ephemeral.dll"
        gcc = os.environ.get("CC", "C:/msys64/ucrt64/bin/gcc.exe" if os.name == "nt" else "gcc")
        sources = [ROOT / "board/src/ps/src" / name for name in ("session.c", "protocol.c", "ephemeral.c", "m09_mlkem.c")]
        sources += [ROOT / "board/src/third_party/tinycrypt/lib/source" / name for name in ("sha256.c", "utils.c")]
        include = [ROOT / name for name in ("board/src/ps/include", "board/src/third_party", "board/src/third_party/mlkem", "board/src/third_party/tinycrypt/lib/include")]
        subprocess.run([gcc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-shared", "-fPIC",
                        *[arg for path in include for arg in ("-I", str(path))], *map(str, sources), "-o", str(library)], check=True)
        cls.lib = ct.CDLL(str(library))
        setup(cls.lib)
        cls.lib.eye_ephemeral_offer.argtypes = [ct.c_void_p] * 3
        cls.lib.eye_ephemeral_complete.argtypes = [ct.c_void_p] * 3 + [ct.c_size_t]
        cls.lib.eye_ephemeral_wipe.argtypes = [ct.c_void_p]
        prior_cc = os.environ.get("CC")
        os.environ["CC"] = gcc
        try:
            cls.kem = Kem(build(cls.path / "kem.dll"))
        finally:
            if prior_cc is None:
                os.environ.pop("CC", None)
            else:
                os.environ["CC"] = prior_cc

    @classmethod
    def tearDownClass(cls):
        if os.name == "nt":
            import _ctypes
            _ctypes.FreeLibrary(cls.kem.lib._handle)
            _ctypes.FreeLibrary(cls.lib._handle)
        cls.temp.cleanup()

    def handshake(self):
        vector = json.loads((ROOT / "data/kat/nist_mlkem512.json").read_text())["encapsulation"][0]
        pk, shared = bytes.fromhex(vector["ek"]), bytes.fromhex(vector["k"])
        hello = record(1, b"\x01\x01\x00\x02" + bytes([1]) * 32)
        ack = record(2, b"\x01\x01\x00\x02" + bytes([2]) * 32)
        kem = record(3, bytes.fromhex(vector["c"]))
        s, e = Session(), Ephemeral()
        self.assertEqual(ct.sizeof(s), 192)
        self.assertEqual(self.lib.eye_session_init(ct.byref(s), array(pk)), 0)
        self.assertEqual(self.lib.eye_session_begin(ct.byref(s), array(shared), array(hello), array(ack), array(kem)), 0)
        finished = (ct.c_ubyte * 44)()
        self.assertEqual(self.lib.eye_session_board_finished(ct.byref(s), finished), 0)
        bootstrap_th, bootstrap_control = bytes(s.transcript_hash), bytes(s.control_key)
        host_finished = record(5, hmac.digest(bootstrap_control, b"host finished" + bootstrap_th, "sha256"))
        self.assertEqual(self.lib.eye_session_verify_host_finished(ct.byref(s), array(host_finished)), 0)
        coins = bytes(range(64))  # Public deterministic test material, never a real identity.
        self.assertEqual(self.lib.eye_ephemeral_offer(ct.byref(e), ct.byref(s), array(coins)), 0)
        offer = bytes(e.offer)
        self.assertEqual(bytes(s.video_key), bytes(16))
        expected_pk, sk = self.kem.keygen(coins)
        self.assertEqual(offer[44:844], expected_pk)
        self.assertEqual(offer[844:], hmac.digest(bootstrap_control, b"EYEPQC eph offer v1" + bootstrap_th + offer[:844], "sha256"))
        ciphertext, business_shared = self.kem.encaps(expected_pk, bytes(range(32)))
        reply = record(11, bootstrap_th + ciphertext + bytes(32))
        reply = reply[:812] + hmac.digest(bootstrap_control, b"EYEPQC eph reply v1" + bootstrap_th + offer + reply[:812], "sha256")
        business_th = hashlib.sha256(b"EYEPQC eph business v1" + bootstrap_th + offer + reply).digest()
        derived = hkdf(business_shared, business_th)
        fixture = dict(test_only=True, hello=hello.hex(), ack=ack.hex(), identity_kem=kem.hex(),
                       identity_public_key=pk.hex(), bootstrap_shared=shared.hex(), bootstrap_th=bootstrap_th.hex(),
                       bootstrap_board_finished=bytes(finished).hex(), bootstrap_host_finished=host_finished.hex(),
                       bootstrap_control_key=bootstrap_control.hex(), offer=offer.hex(), reply=reply.hex(),
                       keygen_coins=coins.hex(), encaps_coins=bytes(range(32)).hex(),
                       business_shared=business_shared.hex(), business_th=business_th.hex(), business_material=derived.hex())
        sk[:] = bytes(len(sk))
        business_shared[:] = bytes(32)
        return s, e, reply, fixture

    def test_success_and_public_fixture(self):
        s, e, reply, fixture = self.handshake()
        self.assertEqual(self.lib.eye_ephemeral_complete(ct.byref(e), ct.byref(s), array(reply), len(reply)), 0)
        self.assertEqual(bytes(e), bytes(ct.sizeof(e)))
        derived = bytes.fromhex(fixture["business_material"])
        self.assertEqual(bytes(s.transcript_hash).hex(), fixture["business_th"])
        self.assertEqual(bytes(s.video_key), derived[:16])
        self.assertEqual(bytes(s.control_key), derived[16:48])
        self.assertEqual(s.state, 2)
        self.assertEqual(s.host_finished_verified, 0)
        early_start = record(6, bytes(40))
        self.assertNotEqual(self.lib.eye_session_command(ct.byref(s), array(early_start)), 0)
        finished = (ct.c_ubyte * 44)()
        self.assertEqual(self.lib.eye_session_board_finished(ct.byref(s), finished), 0)
        self.assertEqual(bytes(finished), record(4, hmac.digest(derived[16:48], b"board finished" + bytes(s.transcript_hash), "sha256")))
        host = record(5, hmac.digest(derived[16:48], b"host finished" + bytes(s.transcript_hash), "sha256"))
        self.assertEqual(self.lib.eye_session_verify_host_finished(ct.byref(s), array(host)), 0)
        start = record(6, bytes(8) + bytes(32))
        start = start[:20] + hmac.digest(derived[16:48], b"host command" + bytes(s.transcript_hash) + start[:20], "sha256")
        self.assertEqual(self.lib.eye_session_command(ct.byref(s), array(start)), 0)
        fixture.update(business_board_finished=bytes(finished).hex(), business_host_finished=host.hex(), business_start=start.hex())
        path = ROOT / "board/output/account_ephemeral_fixture_20261014"
        path.mkdir(parents=True, exist_ok=True)
        (path / "fixture.json").write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")

    def test_tamper_length_direction_replay_wipe(self):
        for position in (5, 12, 44, 843):
            with self.subTest(position=position):
                s, e, reply, _ = self.handshake()
                changed = bytearray(reply)
                changed[position] ^= 1
                self.assertNotEqual(self.lib.eye_ephemeral_complete(ct.byref(e), ct.byref(s), array(changed), len(changed)), 0)
                self.assertEqual(bytes(e), bytes(ct.sizeof(e)))
                self.assertEqual(bytes(s.control_key) + bytes(s.video_key), bytes(48))
        s, e, reply, _ = self.handshake()
        self.assertNotEqual(self.lib.eye_ephemeral_complete(ct.byref(e), ct.byref(s), array(reply), len(reply) - 1), 0)
        self.assertEqual(bytes(e), bytes(ct.sizeof(e)))
        s, e, reply, _ = self.handshake()
        self.assertEqual(self.lib.eye_ephemeral_complete(ct.byref(e), ct.byref(s), array(reply), len(reply)), 0)
        self.assertNotEqual(self.lib.eye_ephemeral_complete(ct.byref(e), ct.byref(s), array(reply), len(reply)), 0)
        self.assertEqual(bytes(s.control_key), bytes(32))

    def test_duplicate_offer_and_suite_mismatch(self):
        s, e, _, _ = self.handshake()
        self.assertNotEqual(self.lib.eye_ephemeral_offer(ct.byref(e), ct.byref(s), array(bytes(64))), 0)
        self.assertEqual(bytes(e), bytes(ct.sizeof(e)))
        self.assertEqual(bytes(s.control_key), bytes(32))
        vector = json.loads((ROOT / "data/kat/nist_mlkem512.json").read_text())["encapsulation"][0]
        s = Session()
        self.assertEqual(self.lib.eye_session_init(ct.byref(s), array(bytes.fromhex(vector["ek"]))), 0)
        hello = record(1, b"\x01\x01\x00\x02" + bytes(32))
        ack = record(2, b"\x01\x01\x00\x01" + bytes(32))
        kem = record(3, bytes.fromhex(vector["c"]))
        self.assertNotEqual(self.lib.eye_session_begin(ct.byref(s), array(bytes.fromhex(vector["k"])), array(hello), array(ack), array(kem)), 0)
        self.assertEqual(bytes(s.control_key), bytes(32))


if __name__ == "__main__":
    unittest.main()
