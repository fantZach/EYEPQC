"""G6 host-to-C-session integration over a fragmented in-memory USB stream.

Synthetic JPEG/software GCM only; never opens a port or accesses a board.
"""
import ctypes as ct
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/host'))
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image
from g6_board import handshake, frames
from handshake import HostSession
from m09 import Kem, build
from protocol import (MessageType, USB_CONTROL, USB_VIDEO, UsbRecordDecoder,
                      decode_control, encode_control, encode_usb_record, encode_video, packet_header)
from test_m10 import Session, array, setup


class MemoryBoard:
    def __init__(self, lib, kem, pk, sk, fault=None):
        self.lib, self.kem, self.sk, self.fault = lib, kem, sk, fault
        self.session = Session()
        assert lib.eye_session_init(ct.byref(self.session), array(pk)) == 0
        self.decoder = UsbRecordDecoder()
        self.pending = bytearray()
        self.read_count = 0

    def write(self, record):
        for channel, message in self.decoder.feed(record):
            assert channel == USB_CONTROL
            kind, body = decode_control(message)
            if kind == MessageType.HELLO:
                self.hello = message
                self.ack = encode_control(MessageType.HELLO_ACK, b'\x01\x01\x00\x01' + secrets.token_bytes(32))
                self.pending.extend(encode_usb_record(USB_CONTROL, self.ack))
            elif kind == MessageType.KEM_CIPHERTEXT:
                shared = self.kem.decaps(self.sk, body)
                assert self.lib.eye_session_begin(ct.byref(self.session), array(shared), array(self.hello),
                                                 array(self.ack), array(message)) == 0
                finished = (ct.c_ubyte * 44)()
                assert self.lib.eye_session_board_finished(ct.byref(self.session), finished) == 0
                self.pending.extend(encode_usb_record(USB_CONTROL, bytes(finished)))
            elif kind == MessageType.FINISHED_HOST:
                self.lib.eye_session_verify_host_finished(ct.byref(self.session), array(message))
            else:
                assert self.lib.eye_session_command(ct.byref(self.session), array(message)) == 0
                if kind == MessageType.START:
                    self.video()
        return len(record)

    def flush(self):
        pass

    def read(self, size):
        # Handshake and video traverse the same real stream decoder, including split headers.
        self.read_count += 1
        take = min(size, (1, 5, 997, 4096)[self.read_count % 4], len(self.pending))
        result = bytes(self.pending[:take])
        del self.pending[:take]
        return result

    def video(self):
        aes = AESGCM(bytes(self.session.video_key))
        for frame_id in range(3):
            buffer = BytesIO()
            Image.new('RGB', (640, 480), (frame_id * 70, 120, 180)).save(buffer, format='JPEG')
            jpeg = buffer.getvalue()
            for packet_id, offset in enumerate(range(0, len(jpeg), 1400)):
                nonce = (ct.c_ubyte * 12)()
                sequence = self.session.packet_sequence
                assert self.lib.eye_session_next_nonce(ct.byref(self.session), nonce) == 0
                header = packet_header(self.session.session_id, frame_id, len(jpeg), packet_id,
                                       frame_id * 40000, sequence)
                payload = jpeg[offset:offset + 1400]
                sealed = aes.encrypt(bytes(nonce), payload, header.pack())
                packet = encode_video(header, sealed[:-16], sealed[-16:])
                first = frame_id == packet_id == 0
                if first and self.fault == 'tag':
                    packet = packet[:-1] + bytes([packet[-1] ^ 1])
                self.pending.extend(encode_usb_record(USB_VIDEO, packet))
                if first and self.fault == 'replay':
                    self.pending.extend(encode_usb_record(USB_VIDEO, packet))


class G6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='eyepqc-g6-')
        folder = Path(cls.temp.name)
        cls.kem = Kem(build(folder / 'kem.dll'))
        library = folder / 'session.dll'
        sources = ['src/ps/src/session.c', 'src/ps/src/protocol.c',
                   'src/third_party/tinycrypt/lib/source/sha256.c',
                   'src/third_party/tinycrypt/lib/source/utils.c']
        subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-shared', '-fPIC', '-I', str(ROOT / 'src/ps/include'), '-I',
                        str(ROOT / 'src/third_party/tinycrypt/lib/include'),
                        *[str(ROOT / p) for p in sources], '-o', str(library)], check=True)
        cls.lib = ct.CDLL(str(library))
        setup(cls.lib)
        vector = json.loads((ROOT / 'data/kat/nist_mlkem512.json').read_text())['encapsulation'][0]
        cls.pk, cls.sk = bytes.fromhex(vector['ek']), bytes.fromhex(vector['dk'])

    @classmethod
    def tearDownClass(cls):
        if os.name == 'nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.lib._handle)
            _ctypes.FreeLibrary(cls.kem.lib._handle)
        del cls.lib, cls.kem
        cls.temp.cleanup()

    def create_pair(self, fault=None):
        return (MemoryBoard(self.lib, self.kem, self.pk, self.sk, fault),
                HostSession(self.pk, hashlib.sha256(self.pk).digest(), self.kem))

    def test_twenty_authenticated_rekeys(self):
        board, host = self.create_pair()
        ids, keys = set(), set()
        for index in range(20):
            decoder = UsbRecordDecoder()
            handshake(board, decoder, host)
            self.assertEqual(bytes(board.session.video_key), bytes(host.video_key))
            self.assertNotIn(host.session_id, ids)
            self.assertNotIn(bytes(host.video_key), keys)
            ids.add(host.session_id)
            keys.add(bytes(host.video_key))
            result = frames(board, decoder, host, 0.02, Path(self.temp.name) / str(index))
            self.assertEqual(result['frames'], 3)
            board.pending.clear()  # End of the requested receive interval.
            board.write(encode_usb_record(USB_CONTROL, host.command(MessageType.REKEY)))
            self.assertEqual(bytes(board.session.video_key), bytes(16))
            self.assertEqual(bytes(board.session.control_key), bytes(32))
            self.assertIsNone(host.video_key)
        host.close()

    def test_bad_finished_sends_no_video(self):
        board, host = self.create_pair()
        handshake(board, UsbRecordDecoder(), host, bad_finished=True)
        self.assertEqual(board.read(1), b'')
        self.assertEqual(bytes(board.session.video_key), bytes(16))
        host.close('ERROR')

    def test_tamper_and_replay_produce_no_image(self):
        for fault, exception in (('tag', InvalidTag), ('replay', ValueError)):
            board, host = self.create_pair(fault)
            decoder = UsbRecordDecoder()
            handshake(board, decoder, host)
            target = Path(self.temp.name) / fault
            with self.assertRaises(exception):
                frames(board, decoder, host, 0.05, target)
            self.assertFalse(target.exists())
            host.close('ERROR')


if __name__ == '__main__':
    unittest.main(verbosity=2)
