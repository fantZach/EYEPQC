"""M10 offline host handshake/session reference; no socket or live transport."""
import hashlib
import hmac
import struct

from m09 import Kem, PK
from protocol import CONTROL_HEADER, MessageType, decode_control, encode_control, make_nonce

DOMAIN = b"EYEPQC v1"
INFO = b"EYEPQC v1 keys"
ROTATE_AT = (1 << 64) - 65536


def derive(shared, pk, hello, ack, kem):
    if len(shared) != 32 or len(pk) != PK:
        raise ValueError("invalid ML-KEM material")
    for message, kind in ((hello, MessageType.HELLO), (ack, MessageType.HELLO_ACK),
                          (kem, MessageType.KEM_CIPHERTEXT)):
        if decode_control(message)[0] != kind:
            raise ValueError("invalid handshake message order")
    transcript = hashlib.sha256(DOMAIN + hashlib.sha256(pk).digest() + hello + ack + kem).digest()
    prk = hmac.digest(transcript, shared, "sha256")
    first = hmac.digest(prk, INFO + b"\x01", "sha256")
    second = hmac.digest(prk, first + INFO + b"\x02", "sha256")
    return transcript, first + second[:24]


class HostSession:
    def __init__(self, pk, pinned_sha256, kem=None):
        if len(pk) != PK or not hmac.compare_digest(hashlib.sha256(pk).digest(), pinned_sha256):
            raise ValueError("pinned ML-KEM public key mismatch")
        self.pk = pk
        self.kem = kem or Kem()
        self.last_transcript = None
        self.state = "IDLE"
        self._clear()

    def _clear(self):
        for name in ("video_key", "control_key"):
            secret = getattr(self, name, None)
            if secret is not None:
                secret[:] = bytes(len(secret))
        self.video_key = self.control_key = None
        self.transcript = None
        self.epoch = self.session_id = self.packet_sequence = self.command_sequence = 0
        self.receive_high = self.receive_mask = None
        self.board_verified = False

    def close(self, state="IDLE"):
        if self.transcript is not None:
            self.last_transcript = self.transcript
        self._clear()
        self.state = state

    def begin(self, host_random, board_random, coins):
        if self.state not in ("IDLE", "REKEY", "ERROR"):
            raise ValueError("handshake already active")
        if len(host_random) != 32 or len(board_random) != 32 or len(coins) != 32:
            raise ValueError("fresh randomness must be 32 bytes per field")
        hello = encode_control(MessageType.HELLO, b"\x01\x01\x00\x01" + host_random)
        ack = encode_control(MessageType.HELLO_ACK, b"\x01\x01\x00\x01" + board_random)
        ciphertext, shared = self.kem.encaps(self.pk, coins)
        kem = encode_control(MessageType.KEM_CIPHERTEXT, ciphertext)
        self.state = "HANDSHAKE"
        transcript, material = derive(shared, self.pk, hello, ack, kem)
        if transcript == self.last_transcript:
            self.close("ERROR")
            raise ValueError("replayed handshake transcript")
        self.transcript = transcript
        self.video_key = bytearray(material[:16])
        self.control_key = bytearray(material[16:48])
        self.epoch, self.session_id = struct.unpack("!II", material[48:])
        self.state = "CONFIRM"
        return hello, ack, kem

    def verify_board_finished(self, message):
        if self.state != "CONFIRM" or self.board_verified:
            raise ValueError("unexpected board Finished")
        kind, body = decode_control(message)
        expected = hmac.digest(self.control_key, b"board finished" + self.transcript, "sha256")
        if kind != MessageType.FINISHED_BOARD or not hmac.compare_digest(body, expected):
            self.close("ERROR")
            raise ValueError("board Finished authentication failed")
        self.board_verified = True

    def host_finished(self):
        if self.state != "CONFIRM" or not self.board_verified:
            raise ValueError("board Finished not verified")
        tag = hmac.digest(self.control_key, b"host finished" + self.transcript, "sha256")
        return encode_control(MessageType.FINISHED_HOST, tag)

    def command(self, kind):
        kind = MessageType(kind)
        if (kind == MessageType.START and (self.state != "CONFIRM" or not self.board_verified)) or (
            kind in (MessageType.STOP, MessageType.REKEY) and self.state != "STREAMING"):
            raise ValueError("command not allowed in this state")
        if kind not in (MessageType.START, MessageType.STOP, MessageType.REKEY):
            raise ValueError("not an authenticated host command")
        if self.command_sequence == (1 << 64) - 1:
            self.close("REKEY")
            raise ValueError("command counter exhausted")
        sequence = self.command_sequence.to_bytes(8, "big")
        prefix = CONTROL_HEADER.pack(b"EYPQ", 1, kind, 0, 40)
        tag = hmac.digest(self.control_key, b"host command" + self.transcript + prefix + sequence,
                          "sha256")
        message = encode_control(kind, sequence + tag)
        self.command_sequence += 1
        if kind == MessageType.START:
            self.state = "STREAMING"
        else:
            self.close("REKEY" if kind == MessageType.REKEY else "IDLE")
        return message

    def next_nonce(self):
        if self.state != "STREAMING":
            raise ValueError("video disabled before Finished/START")
        if self.packet_sequence >= ROTATE_AT:
            self.close("REKEY")
            raise ValueError("packet counter near limit; rekey required")
        sequence = self.packet_sequence
        self.packet_sequence += 1  # Never recycle even if encryption/sending fails.
        return sequence, make_nonce(self.epoch, sequence)

    def accept_authenticated_packet(self, session_id, sequence):
        if self.state != "STREAMING" or session_id != self.session_id or not 0 <= sequence < 1 << 64:
            return False
        if self.receive_high is None:
            self.receive_high, self.receive_mask = sequence, 1
            return True
        if sequence > self.receive_high:
            distance = sequence - self.receive_high
            self.receive_mask = 1 if distance >= 64 else ((self.receive_mask << distance) | 1) & ((1 << 64) - 1)
            self.receive_high = sequence
            return True
        distance = self.receive_high - sequence
        if distance >= 64 or self.receive_mask & (1 << distance):
            return False
        self.receive_mask |= 1 << distance
        return True
