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
from g6_board import (handshake, frames, require_minimum_frames, read_control,
                      drain_rekey, video_records)
from handshake import HostSession
from m09 import Kem, build
from demo_recording import FrameRecording, recording_frames
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
                if frame_id == 0 and packet_id == 1 and self.fault == 'missing':
                    continue
                first = frame_id == packet_id == 0
                if first and self.fault == 'tag':
                    packet = packet[:-1] + bytes([packet[-1] ^ 1])
                if first and self.fault == 'forged-header':
                    forged = bytearray(packet)
                    forged[8:12] = (0xfefefefe).to_bytes(4, 'big')
                    forged[32:40] = (0xfefefefefefefefe).to_bytes(8, 'big')
                    packet = bytes(forged)
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

    def test_coalesced_controls_preserve_every_record(self):
        ack = encode_control(MessageType.HELLO_ACK, b'\x01\x01\x00\x01' + bytes(32))
        finished = encode_control(MessageType.FINISHED_BOARD, bytes(32))
        data = (encode_usb_record(USB_CONTROL, ack) +
                encode_usb_record(USB_CONTROL, finished) +
                encode_usb_record(USB_VIDEO, b'pending video'))

        class Coalesced:
            def read(self, size):
                nonlocal data
                result, data = data, b''
                return result

        reader, decoder = Coalesced(), UsbRecordDecoder()
        self.assertEqual(read_control(reader, decoder), ack)
        self.assertEqual(read_control(reader, decoder), finished)
        self.assertEqual(video_records(reader, decoder), [(USB_VIDEO, b'pending video')])

    def test_rekey_drains_fragmented_old_video_before_new_handshake(self):
        board, host = self.create_pair()
        decoder = UsbRecordDecoder()
        handshake(board, decoder, host)
        old_key = bytes(host.video_key)
        self.assertEqual(decoder.feed(board.read(1)), [])
        self.assertTrue(decoder.buffer)
        board.write(encode_usb_record(USB_CONTROL, host.command(MessageType.REKEY)))
        drain_rekey(board, decoder, timeout=0.2, quiet=0.001)
        self.assertFalse(board.pending)
        self.assertFalse(decoder.buffer)
        handshake(board, decoder, host)
        self.assertNotEqual(bytes(host.video_key), old_key)
        result = frames(board, decoder, host, 0.02, Path(self.temp.name) / 'tail-rekey')
        self.assertEqual(result['frames'], 3)
        host.close()

    def test_rekey_drain_rejects_truncation_and_never_quiet_stream(self):
        class Source:
            def __init__(self, data, repeat=False):
                self.data, self.repeat = data, repeat

            def read(self, size):
                data = self.data
                if not self.repeat:
                    self.data = b''
                return data

        truncated = encode_usb_record(USB_VIDEO, b'old video')[:-1]
        with self.assertRaisesRegex(ValueError, 'truncated USB record'):
            drain_rekey(Source(truncated), UsbRecordDecoder(), timeout=0.1, quiet=0.001)
        with self.assertRaisesRegex(TimeoutError, 'did not become quiet'):
            drain_rekey(Source(encode_usb_record(USB_VIDEO, b'old video'), True),
                        UsbRecordDecoder(), timeout=0.01, quiet=0.001)

    def test_tamper_and_replay_produce_no_image(self):
        for fault, expected_error in (('tag', 'auth_failures'), ('forged-header', 'auth_failures'),
                                      ('replay', 'replay_rejects'), ('missing', 'sequence_gaps')):
            board, host = self.create_pair(fault)
            decoder = UsbRecordDecoder()
            handshake(board, decoder, host)
            target = Path(self.temp.name) / fault
            result = frames(board, decoder, host, 0.05, target)
            self.assertEqual(result['frames'], 2)
            self.assertGreaterEqual(result['errors'][expected_error], 1)
            if fault == 'forged-header':
                self.assertEqual(result['errors'].get('frame_gaps', 0), 1)
                self.assertLess(result['errors']['frame_gaps'], 0xfefefefe)
            self.assertTrue((target / 'first.jpg').is_file())
            host.close('ERROR')

    def test_usb_framing_damage_is_fatal_without_resync_scan(self):
        board, host = self.create_pair()
        decoder = UsbRecordDecoder()
        handshake(board, decoder, host)
        board.pending[:0] = b'\xff\xff\x01'
        target = Path(self.temp.name) / 'framing'
        with self.assertRaisesRegex(ValueError, 'invalid USB record header'):
            frames(board, decoder, host, 0.05, target)
        self.assertFalse(target.exists())
        host.close('ERROR')

    def test_recording_observer_receives_only_verified_complete_frames(self):
        board, host = self.create_pair('tag')
        decoder = UsbRecordDecoder()
        handshake(board, decoder, host)
        recording = FrameRecording(Path(self.temp.name) / 'authenticated-recording', {'mode': 'test'})
        accepted_ids = []
        def accepted(jpeg, header, stats):
            accepted_ids.append(header.frame_id)
            recording.write(jpeg, header)
        try:
            result = frames(board, decoder, host, .05, Path(self.temp.name) / 'recorded-frames',
                            on_frame=accepted)
        finally:
            recording.close()
            host.close('ERROR')
        self.assertEqual(accepted_ids, [1, 2])
        self.assertEqual(result['errors']['auth_failures'], 1)
        self.assertEqual([row['frame_id'] for row, _ in recording_frames(recording.folder)], [1, 2])

    def test_zero_authenticated_frames_is_not_a_pass(self):
        board, host = self.create_pair()
        decoder = UsbRecordDecoder()
        handshake(board, decoder, host)
        board.pending.clear()
        result = frames(board, decoder, host, 0.02, Path(self.temp.name) / 'zero')
        self.assertEqual(result['frames'], 0)
        with self.assertRaisesRegex(RuntimeError, 'insufficient authenticated G6 frames'):
            require_minimum_frames(result)
        host.close('ERROR')


if __name__ == '__main__':
    unittest.main(verbosity=2)
