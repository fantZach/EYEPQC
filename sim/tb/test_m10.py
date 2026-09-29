"""Run: python sim/tb/test_m10.py (C compiler required)."""
import ctypes as ct
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/host"))
from handshake import HostSession, ROTATE_AT, derive
from m09 import Kem, build as build_kem
from protocol import MessageType


class Session(ct.Structure):
    _fields_ = [("pinned_pk_hash", ct.c_ubyte * 32), ("last_transcript", ct.c_ubyte * 32),
                ("transcript_hash", ct.c_ubyte * 32), ("video_key", ct.c_ubyte * 16),
                ("control_key", ct.c_ubyte * 32), ("nonce_prefix", ct.c_uint32),
                ("session_id", ct.c_uint32), ("packet_sequence", ct.c_uint64),
                ("command_sequence", ct.c_uint64), ("receive_high", ct.c_uint64),
                ("receive_mask", ct.c_uint64), ("receive_started", ct.c_uint8),
                ("board_finished_sent", ct.c_uint8), ("host_finished_verified", ct.c_uint8),
                ("state", ct.c_uint8)]


def array(data):
    return (ct.c_ubyte * len(data)).from_buffer_copy(data)


def setup(lib):
    ptr = ct.c_void_p
    for name, count in (("sha256", 3), ("hmac_sha256", 5), ("hkdf56", 3),
                        ("session_init", 2), ("session_begin", 5),
                        ("session_board_finished", 2), ("session_verify_host_finished", 2),
                        ("session_command", 2), ("session_next_nonce", 2),
                        ("session_accept_authenticated_packet", 3)):
        fn = getattr(lib, "eye_" + name)
        fn.argtypes = [ptr] * count
        fn.restype = ct.c_int
    lib.eye_session_accept_authenticated_packet.argtypes = [ptr, ct.c_uint32, ct.c_uint64]
    lib.eye_session_rekey.argtypes = [ptr]


def main():
    with tempfile.TemporaryDirectory(prefix="eyepqc-m10-", ignore_cleanup_errors=True) as temp:
        library = Path(temp) / ("m10.dll" if os.name == "nt" else "m10.so")
        kem_library = Path(temp) / ("kem.dll" if os.name == "nt" else "kem.so")
        subprocess.run([os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-shared", "-fPIC", "-I", str(ROOT / "src/ps/include"), "-I",
                        str(ROOT / "src/third_party/tinycrypt/lib/include"),
                        *[str(ROOT / name) for name in (
                            "src/ps/src/session.c", "src/ps/src/protocol.c",
                            "src/third_party/tinycrypt/lib/source/sha256.c",
                            "src/third_party/tinycrypt/lib/source/utils.c")], "-o", str(library)], check=True)
        kem = Kem(build_kem(kem_library))
        lib = ct.CDLL(str(library))
        setup(lib)
        digest = (ct.c_ubyte * 32)()
        assert lib.eye_sha256(digest, array(b"abc"), 3) == 0
        assert bytes(digest).hex() == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        key = bytes([0x0b]) * 20
        assert lib.eye_hmac_sha256(digest, array(key), len(key), array(b"Hi There"), 8) == 0
        assert bytes(digest).hex() == "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7"
        vectors = json.loads((ROOT / "data/kat/nist_mlkem512.json").read_text())["encapsulation"]
        vector = vectors[0]
        pk, shared = bytes.fromhex(vector["ek"]), bytes.fromhex(vector["k"])
        host = HostSession(pk, hashlib.sha256(pk).digest(), kem)
        hello, ack, encrypted = host.begin(bytes.fromhex("01" * 32), bytes.fromhex("02" * 32),
                                           bytes.fromhex(vector["m"]))
        assert encrypted[12:] == bytes.fromhex(vector["c"])
        board = Session()
        assert ct.sizeof(board) == 192
        assert lib.eye_session_init(ct.byref(board), array(pk)) == 0
        assert lib.eye_session_begin(ct.byref(board), array(shared), array(hello), array(ack), array(encrypted)) == 0
        transcript, material = derive(shared, pk, hello, ack, encrypted)
        assert bytes(board.transcript_hash) == transcript
        assert bytes(board.video_key) == material[:16]
        assert bytes(board.control_key) == material[16:48]
        assert board.nonce_prefix == int.from_bytes(material[48:52], "big")
        assert board.session_id == int.from_bytes(material[52:56], "big")
        assert board.state == 2
        finished = (ct.c_ubyte * 44)()
        assert lib.eye_session_board_finished(ct.byref(board), finished) == 0
        host.verify_board_finished(bytes(finished))
        old_host_finished = host.host_finished()
        assert lib.eye_session_verify_host_finished(ct.byref(board), array(old_host_finished)) == 0
        assert lib.eye_session_command(ct.byref(board), array(host.command(MessageType.START))) == 0
        assert board.state == 3
        nonce = (ct.c_ubyte * 12)()
        for sequence in range(3):
            assert lib.eye_session_next_nonce(ct.byref(board), nonce) == 0
            assert host.next_nonce() == (sequence, bytes(nonce))
        for sequence, accepted in ((1, True), (0, True), (1, False), (65, True), (0, False)):
            c = lib.eye_session_accept_authenticated_packet(ct.byref(board), board.session_id, sequence) == 0
            assert c == accepted == host.accept_authenticated_packet(host.session_id, sequence)
        old_nonce = bytes(nonce)
        old_session_id = board.session_id
        assert lib.eye_session_command(ct.byref(board), array(host.command(MessageType.REKEY))) == 0
        assert board.state == 4 and bytes(board.video_key) == bytes(16)
        assert bytes(board.control_key) == bytes(32) and board.nonce_prefix == 0
        # Reconnection with fresh randoms and a fresh encapsulation does not reuse Key/Nonce.
        hello2, ack2, encrypted2 = host.begin(bytes.fromhex("03" * 32), bytes.fromhex("04" * 32),
                                              bytes.fromhex("05" * 32))
        shared2 = kem.decaps(bytes.fromhex(vector["dk"]), encrypted2[12:])
        assert lib.eye_session_begin(ct.byref(board), array(shared2), array(hello2), array(ack2),
                                     array(encrypted2)) == 0
        assert bytes(board.video_key) != material[:16]
        assert lib.eye_session_board_finished(ct.byref(board), finished) == 0
        assert lib.eye_session_verify_host_finished(ct.byref(board), array(old_host_finished)) == -3
        assert board.state == 5 and bytes(board.control_key) == bytes(32)
        assert old_nonce != host.epoch.to_bytes(4, "big") + bytes(8)
        # Same transcript cannot be reused even after rekey/error recovery.
        assert lib.eye_session_begin(ct.byref(board), array(shared2), array(hello2), array(ack2),
                                     array(encrypted2)) == -3
        # Fresh C session: explicit near-wrap forces rekey without allocating a nonce.
        board2 = Session()
        assert lib.eye_session_init(ct.byref(board2), array(pk)) == 0
        assert lib.eye_session_begin(ct.byref(board2), array(shared2), array(hello2), array(ack2),
                                     array(encrypted2)) == 0
        assert lib.eye_session_board_finished(ct.byref(board2), finished) == 0
        host.verify_board_finished(bytes(finished))
        assert lib.eye_session_verify_host_finished(ct.byref(board2), array(host.host_finished())) == 0
        assert lib.eye_session_command(ct.byref(board2), array(host.command(MessageType.START))) == 0
        assert lib.eye_session_accept_authenticated_packet(ct.byref(board2), old_session_id, 0) == -2
        assert not host.accept_authenticated_packet(old_session_id, 0)
        assert not host.accept_authenticated_packet(host.session_id, -1)
        assert not host.accept_authenticated_packet(host.session_id, 1 << 64)
        board2.packet_sequence = ROTATE_AT
        host.packet_sequence = ROTATE_AT
        assert lib.eye_session_next_nonce(ct.byref(board2), nonce) == -4
        try:
            host.next_nonce()
        except ValueError:
            pass
        else:
            raise AssertionError("host accepted exhausted nonce counter")
        assert board2.state == 4 and host.state == "REKEY"
        print("M10 PC PASS: SHA/HMAC vectors, KDF parity, Finished, command/replay, rekey/zeroize")
        if os.name == "nt":
            import _ctypes
            _ctypes.FreeLibrary(lib._handle)
            _ctypes.FreeLibrary(kem.lib._handle)
        del lib, kem


if __name__ == "__main__":
    main()
