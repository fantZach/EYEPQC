from __future__ import annotations

import ctypes as ct
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class Session(ct.Structure):
    _fields_ = [
        ("pinned_pk_hash", ct.c_ubyte * 32),
        ("last_transcript", ct.c_ubyte * 32),
        ("transcript_hash", ct.c_ubyte * 32),
        ("video_key", ct.c_ubyte * 16),
        ("control_key", ct.c_ubyte * 32),
        ("nonce_prefix", ct.c_uint32),
        ("session_id", ct.c_uint32),
        ("packet_sequence", ct.c_uint64),
        ("command_sequence", ct.c_uint64),
        ("receive_high", ct.c_uint64),
        ("receive_mask", ct.c_uint64),
        ("receive_started", ct.c_uint8),
        ("board_finished_sent", ct.c_uint8),
        ("host_finished_verified", ct.c_uint8),
        ("state", ct.c_uint8),
    ]


def as_buffer(data: bytes):
    return (ct.c_ubyte * len(data)).from_buffer_copy(data)


class SessionFailClosedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="eyepqc-session-failclosed-")
        suffix = ".dll" if os.name == "nt" else ".so"
        cls.library_path = Path(cls.temp.name) / ("session" + suffix)
        sources = [
            "board/src/ps/src/session.c",
            "board/src/ps/src/protocol.c",
            "board/src/third_party/tinycrypt/lib/source/sha256.c",
            "board/src/third_party/tinycrypt/lib/source/utils.c",
        ]
        command = [
            os.environ.get("CC", "gcc"), "-std=c11", "-O2", "-Wall", "-Wextra",
            "-Werror", "-shared", "-fPIC", "-I", str(ROOT / "board/src/ps/include"),
            "-I", str(ROOT / "board/src/third_party/tinycrypt/lib/include"),
            *(str(ROOT / source) for source in sources), "-o", str(cls.library_path),
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        cls.lib = ct.CDLL(str(cls.library_path))
        cls.lib.eye_sha256.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_size_t]
        cls.lib.eye_sha256.restype = ct.c_int
        cls.lib.eye_hmac_sha256.argtypes = [
            ct.c_void_p, ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_size_t,
        ]
        cls.lib.eye_hmac_sha256.restype = ct.c_int
        cls.lib.eye_hkdf56.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_void_p]
        cls.lib.eye_hkdf56.restype = ct.c_int
        cls.lib.eye_session_init.argtypes = [ct.c_void_p, ct.c_void_p]
        cls.lib.eye_session_init.restype = ct.c_int
        cls.lib.eye_session_begin.argtypes = [ct.c_void_p] * 5
        cls.lib.eye_session_begin.restype = ct.c_int
        cls.lib.eye_session_verify_host_finished.argtypes = [ct.c_void_p, ct.c_void_p]
        cls.lib.eye_session_verify_host_finished.restype = ct.c_int
        cls.lib.eye_session_board_finished.argtypes = [ct.c_void_p, ct.c_void_p]
        cls.lib.eye_session_board_finished.restype = ct.c_int
        cls.lib.eye_session_command.argtypes = [ct.c_void_p, ct.c_void_p]
        cls.lib.eye_session_command.restype = ct.c_int
        cls.lib.eye_session_next_nonce.argtypes = [ct.c_void_p, ct.c_void_p]
        cls.lib.eye_session_next_nonce.restype = ct.c_int
        cls.lib.eye_session_accept_authenticated_packet.argtypes = [
            ct.c_void_p, ct.c_uint32, ct.c_uint64,
        ]
        cls.lib.eye_session_accept_authenticated_packet.restype = ct.c_int
        cls.lib.eye_control_encode.argtypes = [
            ct.c_void_p, ct.c_size_t, ct.c_uint8, ct.c_void_p, ct.c_size_t,
        ]
        cls.lib.eye_control_encode.restype = ct.c_int

    @classmethod
    def tearDownClass(cls):
        if os.name == "nt":
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
        del cls.lib
        cls.temp.cleanup()

    @staticmethod
    def filled(size: int, value: int = 0xA5):
        return (ct.c_ubyte * size)(*([value] * size))

    def make_active_session(self) -> Session:
        session = Session()
        session.pinned_pk_hash[:] = bytes([0x11] * 32)
        session.last_transcript[:] = bytes([0x22] * 32)
        session.transcript_hash[:] = bytes([0x33] * 32)
        session.video_key[:] = bytes([0x44] * 16)
        session.control_key[:] = bytes([0x55] * 32)
        session.nonce_prefix = 0x66778899
        session.session_id = 0xAABBCCDD
        session.packet_sequence = 7
        session.command_sequence = 3
        session.receive_high = 9
        session.receive_mask = 0x101
        session.receive_started = 1
        session.board_finished_sent = 1
        session.host_finished_verified = 1
        session.state = 3  # EYE_STATE_STREAMING
        return session

    def assert_session_retired(self, session: Session, *, keep_pins: bool = True):
        self.assertEqual(bytes(session.transcript_hash), bytes(32))
        self.assertEqual(bytes(session.video_key), bytes(16))
        self.assertEqual(bytes(session.control_key), bytes(32))
        self.assertEqual(session.nonce_prefix, 0)
        self.assertEqual(session.session_id, 0)
        self.assertEqual(session.packet_sequence, 0)
        self.assertEqual(session.command_sequence, 0)
        self.assertEqual(session.receive_high, 0)
        self.assertEqual(session.receive_mask, 0)
        self.assertEqual(session.receive_started, 0)
        self.assertEqual(session.board_finished_sent, 0)
        self.assertEqual(session.host_finished_verified, 0)
        self.assertEqual(session.state, 5)  # EYE_STATE_ERROR
        if keep_pins:
            self.assertEqual(bytes(session.pinned_pk_hash), bytes([0x11] * 32))
            self.assertEqual(bytes(session.last_transcript), bytes([0x33] * 32))

    def test_hash_and_hmac_outputs_are_zeroed_on_invalid_arguments(self):
        digest = self.filled(32)
        self.assertEqual(self.lib.eye_sha256(digest, None, 1), -1)
        self.assertEqual(bytes(digest), bytes(32))

        digest = self.filled(32)
        message = as_buffer(b"message")
        self.assertEqual(self.lib.eye_hmac_sha256(digest, None, 32, message, 7), -1)
        self.assertEqual(bytes(digest), bytes(32))

    def test_hkdf_output_is_zeroed_on_invalid_arguments(self):
        output = self.filled(56)
        salt = self.filled(32, 0x5A)
        self.assertEqual(self.lib.eye_hkdf56(output, None, salt), -1)
        self.assertEqual(bytes(output), bytes(56))

    def test_invalid_reinitialization_clears_prior_session(self):
        session = self.make_active_session()
        self.assertEqual(self.lib.eye_session_init(ct.byref(session), None), -1)
        self.assertEqual(bytes(session), bytes(ct.sizeof(session)))

    def test_invalid_begin_and_malformed_finished_retire_active_keys(self):
        session = self.make_active_session()
        self.assertEqual(
            self.lib.eye_session_begin(ct.byref(session), None, None, None, None), -1)
        self.assert_session_retired(session)

        session = self.make_active_session()
        session.state = 2  # EYE_STATE_CONFIRM
        session.host_finished_verified = 0
        malformed = as_buffer(bytes(44))
        self.assertEqual(
            self.lib.eye_session_verify_host_finished(ct.byref(session), malformed), -1)
        self.assert_session_retired(session)

    def test_malformed_commands_and_sequence_mismatch_retire_active_keys(self):
        session = self.make_active_session()
        malformed = as_buffer(bytes(52))
        self.assertEqual(self.lib.eye_session_command(ct.byref(session), malformed), -1)
        self.assert_session_retired(session)

        session = self.make_active_session()
        body_bytes = bytearray(40)
        body_bytes[7] = 1  # STOP with a sequence different from command_sequence.
        body = as_buffer(body_bytes)
        command = (ct.c_ubyte * 52)()
        self.assertEqual(self.lib.eye_control_encode(command, 52, 7, body, 40), 0)
        self.assertEqual(self.lib.eye_session_command(ct.byref(session), command), -3)
        self.assert_session_retired(session)

    def test_null_finished_or_nonce_output_retires_active_keys(self):
        session = self.make_active_session()
        session.state = 2  # EYE_STATE_CONFIRM
        self.assertEqual(self.lib.eye_session_board_finished(ct.byref(session), None), -1)
        self.assert_session_retired(session)

        session = self.make_active_session()
        self.assertEqual(self.lib.eye_session_next_nonce(ct.byref(session), None), -1)
        self.assert_session_retired(session)

    def test_finished_and_nonce_output_buffers_are_zeroed_on_error(self):
        session = self.make_active_session()
        finished = self.filled(44)
        self.assertEqual(
            self.lib.eye_session_board_finished(ct.byref(session), finished), -2)
        self.assertEqual(bytes(finished), bytes(44))

        session = self.make_active_session()
        nonce = self.filled(12)
        session.state = 2  # EYE_STATE_CONFIRM, not STREAMING.
        self.assertEqual(self.lib.eye_session_next_nonce(ct.byref(session), nonce), -2)
        self.assertEqual(bytes(nonce), bytes(12))

        session = self.make_active_session()
        nonce = self.filled(12)
        session.packet_sequence = (1 << 64) - 1 - 65535
        self.assertEqual(self.lib.eye_session_next_nonce(ct.byref(session), nonce), -4)
        self.assertEqual(bytes(nonce), bytes(12))
        self.assertEqual(session.state, 4)  # EYE_STATE_REKEY

    def test_authenticated_packet_replay_rejection_preserves_active_session(self):
        session = self.make_active_session()
        session.receive_started = 0
        session.receive_high = 0
        session.receive_mask = 0
        session_id = session.session_id
        video_key = bytes(session.video_key)
        control_key = bytes(session.control_key)

        accept = self.lib.eye_session_accept_authenticated_packet
        self.assertEqual(accept(ct.byref(session), session_id, 10), 0)
        self.assertEqual(accept(ct.byref(session), session_id, 8), 0)
        self.assertEqual(accept(ct.byref(session), session_id, 9), 0)
        accepted_window = (session.receive_high, session.receive_mask)

        self.assertEqual(accept(ct.byref(session), session_id, 10), -3)
        self.assertEqual((session.receive_high, session.receive_mask), accepted_window)
        self.assertEqual(accept(ct.byref(session), session_id ^ 1, 11), -2)
        self.assertEqual((session.receive_high, session.receive_mask), accepted_window)
        self.assertEqual(session.state, 3)  # EYE_STATE_STREAMING
        self.assertEqual(bytes(session.video_key), video_key)
        self.assertEqual(bytes(session.control_key), control_key)

        self.assertEqual(accept(ct.byref(session), session_id, 75), 0)
        advanced_window = (session.receive_high, session.receive_mask)
        self.assertEqual(accept(ct.byref(session), session_id, 11), -3)
        self.assertEqual((session.receive_high, session.receive_mask), advanced_window)
        self.assertEqual(session.state, 3)  # EYE_STATE_STREAMING


if __name__ == "__main__":
    unittest.main()
