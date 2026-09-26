"""EYEPQC v1 wire formats. See doc/protocol.md; no native C struct on wire."""

from dataclasses import dataclass, astuple
from enum import IntEnum
import struct

VERSION = 1
SUITE = 1  # ML-KEM-512 / AES-128-GCM
ENCRYPTED = 1
MAX_PAYLOAD = 1400
MAX_JPEG = 2 * 1024 * 1024
TAG_SIZE = 16
MAX_CONTROL = 1024
VIDEO_HEADER = struct.Struct("!BBHIIHHIHHQQ")
CONTROL_HEADER = struct.Struct("!4sBBHI")
NONCE = struct.Struct("!IQ")


class MessageType(IntEnum):
    HELLO = 1
    HELLO_ACK = 2
    KEM_CIPHERTEXT = 3
    FINISHED_BOARD = 4
    FINISHED_HOST = 5
    START = 6
    STOP = 7
    REKEY = 8
    ERROR = 9


CONTROL_LENGTHS = {1: 36, 2: 36, 3: 768, 4: 32, 5: 32, 6: 40, 7: 40, 8: 40}


@dataclass(frozen=True)
class VideoHeader:
    version: int
    flags: int
    header_length: int
    session_id: int
    frame_id: int
    packet_id: int
    packet_count: int
    jpeg_length: int
    payload_length: int
    reserved: int
    timestamp: int
    packet_sequence: int

    def validate(self):
        if self.version != VERSION or self.flags not in (0, ENCRYPTED):
            raise ValueError("unsupported version or flags")
        if self.header_length != VIDEO_HEADER.size or self.reserved != 0:
            raise ValueError("invalid header length or reserved bits")
        if not 4 <= self.jpeg_length <= MAX_JPEG:
            raise ValueError("JPEG length out of range")
        count = (self.jpeg_length + MAX_PAYLOAD - 1) // MAX_PAYLOAD
        if self.packet_count != count or not 0 <= self.packet_id < count:
            raise ValueError("invalid packet index/count")
        expected = min(MAX_PAYLOAD, self.jpeg_length - self.packet_id * MAX_PAYLOAD)
        if self.payload_length != expected:
            raise ValueError("inconsistent payload length")
        for name, bits in (("session_id", 32), ("frame_id", 32),
                           ("timestamp", 64), ("packet_sequence", 64)):
            if not 0 <= getattr(self, name) < 1 << bits:
                raise ValueError(f"{name} out of range")

    def pack(self):
        self.validate()
        return VIDEO_HEADER.pack(*astuple(self))

    @classmethod
    def unpack(cls, data):
        if len(data) != VIDEO_HEADER.size:
            raise ValueError("video header must be exactly 40 bytes")
        header = cls(*VIDEO_HEADER.unpack(data))
        header.validate()
        return header


def packet_header(session_id, frame_id, jpeg_length, packet_id, timestamp,
                  packet_sequence, *, encrypted=True):
    count = (jpeg_length + MAX_PAYLOAD - 1) // MAX_PAYLOAD
    header = VideoHeader(VERSION, int(encrypted), VIDEO_HEADER.size, session_id,
                         frame_id, packet_id, count, jpeg_length,
                         min(MAX_PAYLOAD, jpeg_length - packet_id * MAX_PAYLOAD),
                         0, timestamp, packet_sequence)
    header.validate()
    return header


def make_nonce(session_epoch, packet_sequence):
    if not 0 <= session_epoch < 1 << 32 or not 0 <= packet_sequence < 1 << 64:
        raise ValueError("nonce counter out of range")
    return NONCE.pack(session_epoch, packet_sequence)


def encode_video(header, payload, tag=b""):
    aad = header.pack()
    if len(payload) != header.payload_length:
        raise ValueError("payload length mismatch")
    if len(tag) != (TAG_SIZE if header.flags == ENCRYPTED else 0):
        raise ValueError("tag length mismatch")
    return aad + payload + tag


def decode_video(datagram, *, allow_plaintext=False):
    if len(datagram) < VIDEO_HEADER.size:
        raise ValueError("truncated video header")
    aad = datagram[:VIDEO_HEADER.size]
    header = VideoHeader.unpack(aad)
    if header.flags == 0 and not allow_plaintext:
        raise ValueError("plaintext disabled")
    tag_size = TAG_SIZE if header.flags == ENCRYPTED else 0
    if len(datagram) != VIDEO_HEADER.size + header.payload_length + tag_size:
        raise ValueError("datagram length mismatch")
    end = VIDEO_HEADER.size + header.payload_length
    return header, aad, datagram[VIDEO_HEADER.size:end], datagram[end:]


def _control_type(kind, length):
    try:
        kind = MessageType(kind)
    except ValueError as exc:
        raise ValueError("unknown control type") from exc
    if not 0 <= length <= MAX_CONTROL:
        raise ValueError("control message too long")
    if kind == MessageType.ERROR:
        if not 2 <= length <= 258:
            raise ValueError("invalid error length")
    elif length != CONTROL_LENGTHS[kind]:
        raise ValueError("invalid control body length")
    return kind


def _control_prefix(prefix):
    magic, version, kind, reserved, length = CONTROL_HEADER.unpack(prefix)
    if magic != b"EYPQ" or version != VERSION or reserved != 0:
        raise ValueError("invalid control header")
    return _control_type(kind, length), length


def _control_body(kind, body):
    if kind in (MessageType.HELLO, MessageType.HELLO_ACK):
        low, high, suite = struct.unpack("!BBH", body[:4])
        if not low <= VERSION <= high or suite != SUITE:
            raise ValueError("unsupported version range or suite")
        if kind == MessageType.HELLO_ACK and (low, high) != (VERSION, VERSION):
            raise ValueError("HELLO_ACK must select version 1")
    if kind == MessageType.ERROR:
        if not 1 <= int.from_bytes(body[:2], "big") <= 7:
            raise ValueError("unknown error code")
        body[2:].decode("utf-8")


def encode_control(kind, body):
    kind = _control_type(kind, len(body))
    _control_body(kind, body)
    return CONTROL_HEADER.pack(b"EYPQ", VERSION, kind, 0, len(body)) + body


def decode_control(message):
    if len(message) < CONTROL_HEADER.size:
        raise ValueError("truncated control header")
    kind, length = _control_prefix(message[:CONTROL_HEADER.size])
    if len(message) != CONTROL_HEADER.size + length:
        raise ValueError("control length mismatch")
    body = message[CONTROL_HEADER.size:]
    _control_body(kind, body)
    return kind, body


class ControlDecoder:
    """TCP fragmentation/coalescing, buffering at most one bounded message."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        messages = []
        offset = 0
        try:
            while offset < len(data):
                target = CONTROL_HEADER.size
                if len(self.buffer) >= target:
                    _, length = _control_prefix(self.buffer[:target])
                    target += length
                take = min(target - len(self.buffer), len(data) - offset)
                self.buffer.extend(data[offset:offset + take])
                offset += take
                if len(self.buffer) >= CONTROL_HEADER.size:
                    _, length = _control_prefix(self.buffer[:CONTROL_HEADER.size])
                    if len(self.buffer) == CONTROL_HEADER.size + length:
                        messages.append(decode_control(bytes(self.buffer)))
                        self.buffer.clear()
        except ValueError:
            self.buffer.clear()
            raise
        return messages

    def finish(self):
        if self.buffer:
            self.buffer.clear()
            raise ValueError("truncated TCP control message")
