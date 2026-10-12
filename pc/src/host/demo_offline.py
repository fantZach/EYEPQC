"""Clearly synthetic, software-only peer for the demo. Never accesses hardware."""
import hmac
from io import BytesIO
import secrets
import struct
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image, ImageDraw
from handshake import derive, wipe_secret
from protocol import (MessageType, USB_CONTROL, USB_VIDEO, UsbRecordDecoder,
                      VideoHeader, decode_control, encode_control,
                      encode_usb_record, encode_video, make_nonce)


class OfflineBoard:
    def __init__(self, kem, fps=20):
        self.kem = kem
        keygen_coins = bytearray(secrets.token_bytes(64))
        try:
            self.pk, private = kem.keygen(keygen_coins)
        finally:
            wipe_secret(keygen_coins)
        self.sk = private if isinstance(private, bytearray) else bytearray(private)
        self.fps = fps
        self.pending = bytearray()
        self.decoder = UsbRecordDecoder()
        self.video_key = self.control_key = None
        self.streaming = False
        self.phase = 'HELLO'

    def _reply(self, kind, body):
        self.pending.extend(encode_usb_record(USB_CONTROL, encode_control(kind, body)))

    def _clear(self):
        for key in (self.video_key, self.control_key):
            if key is not None:
                key[:] = bytes(len(key))
        self.video_key = self.control_key = None
        self.streaming = False

    def write(self, record):
        for channel, message in self.decoder.feed(record):
            if channel != USB_CONTROL:
                raise ValueError('offline peer expects control')
            kind, body = decode_control(message)
            if kind == MessageType.HELLO and self.phase == 'HELLO':
                self.hello = message
                self.ack = encode_control(MessageType.HELLO_ACK, b'\x01\x01\x00\x01' + secrets.token_bytes(32))
                self.pending.extend(encode_usb_record(USB_CONTROL, self.ack))
                self.phase = 'KEM'
            elif kind == MessageType.KEM_CIPHERTEXT and self.phase == 'KEM':
                shared = material = None
                try:
                    shared = self.kem.decaps(self.sk, body)
                    self.transcript, material = derive(shared, self.pk, self.hello, self.ack, message)
                    view = memoryview(material)
                    self.video_key = bytearray(view[:16])
                    self.control_key = bytearray(view[16:48])
                    self.epoch, self.session_id = struct.unpack('!II', view[48:56])
                finally:
                    wipe_secret(shared)
                    wipe_secret(material)
                self._reply(MessageType.FINISHED_BOARD,
                            hmac.digest(self.control_key, b'board finished' + self.transcript, 'sha256'))
                self.phase = 'FINISHED'
            elif kind == MessageType.FINISHED_HOST and self.phase == 'FINISHED':
                expected = hmac.digest(self.control_key, b'host finished' + self.transcript, 'sha256')
                if not hmac.compare_digest(body, expected):
                    self._clear()
                    self.phase = 'FAULT'
                    continue
                self.command_sequence = 0
                self.phase = 'START'
            elif kind in (MessageType.START, MessageType.REKEY, MessageType.STOP):
                if self.phase != ('START' if kind == MessageType.START else 'STREAM'):
                    raise ValueError('offline command in wrong state')
                sequence = int.from_bytes(body[:8], 'big')
                expected = hmac.digest(self.control_key,
                                       b'host command' + self.transcript + message[:12] + body[:8], 'sha256')
                if sequence != self.command_sequence or not hmac.compare_digest(body[8:], expected):
                    raise ValueError('offline command authentication failed')
                self.command_sequence += 1
                if kind == MessageType.START:
                    self.frame_id = self.sequence = 0
                    self.next_frame = time.monotonic()
                    self.streaming = True
                    self.phase = 'STREAM'
                else:
                    self._clear()
                    self.phase = 'HELLO'
            else:
                raise ValueError('unexpected offline handshake message')
        return len(record)

    def flush(self):
        pass

    def read(self, size):
        if not self.pending and self.streaming and time.monotonic() >= self.next_frame:
            self._video()
            self.next_frame = time.monotonic() + 1 / self.fps
        take = min(size, len(self.pending), 4096)
        data = bytes(self.pending[:take])
        del self.pending[:take]
        if not data:
            time.sleep(.002)
        return data

    def _video(self):
        image = Image.new('RGB', (640, 480), '#172235')
        draw = ImageDraw.Draw(image)
        for x, color in enumerate(('#13b8a6', '#3878e8', '#e8ba43', '#db6387')):
            draw.rectangle((x * 160, 310, (x + 1) * 160, 480), fill=color)
        x = 40 + (self.frame_id * 9) % 540
        draw.ellipse((x, 110, x + 55, 165), fill='#f1f5f9')
        draw.text((25, 30), 'OFFLINE / SYNTHETIC VIDEO', fill='white')
        draw.text((25, 55), f'ML-KEM-512 + AES-GCM software | frame {self.frame_id}', fill='#a7c4da')
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=80)
        jpeg = buffer.getvalue()
        aes = AESGCM(bytes(self.video_key))
        count = (len(jpeg) + 1399) // 1400
        timestamp = time.monotonic_ns() // 1000
        for packet, offset in enumerate(range(0, len(jpeg), 1400)):
            payload = jpeg[offset:offset + 1400]
            header = VideoHeader(1, 1, 40, self.session_id, self.frame_id, packet, count,
                                 len(jpeg), len(payload), 0, timestamp, self.sequence)
            sealed = aes.encrypt(make_nonce(self.epoch, self.sequence), payload, header.pack())
            self.pending.extend(encode_usb_record(USB_VIDEO, encode_video(header, sealed[:-16], sealed[-16:])))
            self.sequence += 1
        self.frame_id += 1

    def close(self):
        self._clear()
        self.sk[:] = bytes(len(self.sk))
        self.pending.clear()
