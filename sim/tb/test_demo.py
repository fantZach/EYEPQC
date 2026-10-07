"""Offline demo control, authenticated recording and replay; hardware access forbidden."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/host'))
from PIL import Image
from demo_controller import DemoController
from demo_offline import OfflineBoard
from demo_recording import FrameRecording, recording_frames
from g6_board import handshake, frames
from handshake import HostSession
from m09 import Kem, build
from protocol import UsbRecordDecoder, packet_header


class Demo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='eyepqc-demo-')
        cls.kem = Kem(build(Path(cls.temp.name) / ('kem.dll' if os.name == 'nt' else 'kem.so')))

    @classmethod
    def tearDownClass(cls):
        if os.name == 'nt':
            import _ctypes
            _ctypes.FreeLibrary(cls.kem.lib._handle)
        del cls.kem
        cls.temp.cleanup()

    def wait(self, controller, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for kind, data in controller.updates():
                if predicate(kind, data):
                    return data
            if not controller.running:
                self.fail('demo worker exited before expected event')
            time.sleep(.01)
        self.fail('expected demo event timeout')

    def test_control_recording_tamper_recovery_and_rekey_without_hardware(self):
        with tempfile.TemporaryDirectory() as out, \
             patch('demo_controller.Kem', return_value=self.kem), \
             patch('demo_controller.port', side_effect=AssertionError('hardware port access')), \
             patch('demo_controller.serial.Serial', side_effect=AssertionError('serial access')), \
             patch('demo_controller.verify_build', side_effect=AssertionError('offline firmware access')):
            controller = DemoController(Path('does-not-exist'), offline=True, output=out, offline_fps=100)
            try:
                self.assertTrue(controller.start())
                self.assertFalse(controller.start())
                self.wait(controller, lambda kind, data: kind == 'state' and data['name'] == 'STREAMING')
                controller.request('record_start')
                record = self.wait(controller, lambda kind, data: kind == 'recording' and data['active'])
                controller.request('tamper')
                self.wait(controller, lambda kind, data: kind == 'stats' and data['errors'].get('auth_failures', 0) == 1)
                before = self.wait(controller, lambda kind, data: kind == 'stats' and data['frames'] >= 5)
                controller.request('rekey')
                changed = self.wait(controller, lambda kind, data: kind == 'session' and data['key_changed'] is True)
                self.assertNotEqual(changed['session_id'], before['session_id'])
                self.wait(controller, lambda kind, data: kind == 'state' and data['name'] == 'STREAMING')
                controller.request('record_stop')
                self.wait(controller, lambda kind, data: kind == 'recording' and not data['active'])
            finally:
                controller.stop()
                controller.thread.join(timeout=5)
            self.assertFalse(controller.running)
            reports = list(Path(out).glob('demo_offline/*/result.json'))
            report = json.loads(reports[0].read_text())
            self.assertEqual(report['status'], 'stopped')
            self.assertFalse(report['board_accessed'])
            self.assertFalse(report['firmware_loaded'])
            self.assertEqual(len(report['sessions']), 2)
            saved = list(recording_frames(record['path']))
            self.assertGreaterEqual(len(saved), 3)
            self.assertEqual(len({row['session_id'] for row, _ in saved}), 2)
            for _, jpeg in saved:
                with Image.open(BytesIO(jpeg)) as image:
                    image.load()
                    self.assertEqual(image.size, (640, 480))

    def test_cancelling_handshake_closes_transport_and_reports_cancelled(self):
        peer = OfflineBoard(self.kem)
        def wait_for_cancel(ser, decoder, session, cancelled=None):
            until = time.monotonic() + 3
            while time.monotonic() < until and not cancelled():
                time.sleep(.005)
            raise InterruptedError('cancelled')
        with tempfile.TemporaryDirectory() as out, \
             patch('demo_controller.Kem', return_value=self.kem), \
             patch('demo_controller.OfflineBoard', return_value=peer), \
             patch('demo_controller.handshake', side_effect=wait_for_cancel):
            controller = DemoController('unused', offline=True, output=out)
            controller.start()
            try:
                self.wait(controller, lambda kind, data: kind == 'state' and data['name'] == 'HANDSHAKE')
            finally:
                controller.stop()
                controller.thread.join(timeout=5)
            self.assertFalse(controller.running)
            self.assertEqual(bytes(peer.sk), bytes(len(peer.sk)))
            report = json.loads(next(Path(out).glob('demo_offline/*/result.json')).read_text())
            self.assertEqual(report['status'], 'cancelled')

    def test_recording_tamper_and_path_substitution_are_rejected(self):
        with tempfile.TemporaryDirectory() as out:
            recorder = FrameRecording(Path(out) / 'recording', {'mode': 'test'})
            header = packet_header(1, 0, 4, 0, 1, 0)
            recorder.write(b'jpeg', header)
            recorder.close()
            self.assertEqual(list(recording_frames(recorder.folder))[0][1], b'jpeg')
            (recorder.folder / '00000000.jpg').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                list(recording_frames(recorder.folder))
            row = json.loads((recorder.folder / 'frames.jsonl').read_text())
            row['file'] = '../outside.jpg'
            (recorder.folder / 'frames.jsonl').write_text(json.dumps(row) + '\n')
            with self.assertRaisesRegex(ValueError, 'invalid recording frame index'):
                list(recording_frames(recorder.folder))

    def test_bad_finished_offline_peer_never_emits_video(self):
        peer = OfflineBoard(self.kem)
        host = HostSession(peer.pk, hashlib.sha256(peer.pk).digest(), self.kem)
        try:
            handshake(peer, UsbRecordDecoder(), host, bad_finished=True)
            self.assertEqual(peer.read(4096), b'')
            self.assertFalse(peer.streaming)
            self.assertIsNone(peer.video_key)
        finally:
            host.close()
            peer.close()

    def test_wrong_public_key_pin_fails_before_port_access(self):
        pk, _ = self.kem.keygen(bytes(64))
        with tempfile.TemporaryDirectory() as out:
            folder = Path(out)
            (folder / 'g6_usb/build').mkdir(parents=True)
            (folder / 'g6_usb_manifest.json').write_text('{}')
            (folder / 'g6_usb/build/g6_usb.elf').write_bytes(b'test identity only')
            (folder / 'public.bin').write_bytes(pk)
            (folder / 'public.sha256').write_text('00' * 32)
            with patch('demo_controller.Kem', return_value=self.kem), \
                 patch('demo_controller.OUT', folder), \
                 patch('demo_controller.verify_build', return_value=({'application': 'g6_usb', 'xsa_sha256': 'test'}, 0)), \
                 patch('demo_controller.port', side_effect=AssertionError('port touched before pin validation')) as port:
                controller = DemoController(folder, output=folder / 'captures')
                controller.start()
                controller.thread.join(timeout=5)
                self.assertFalse(controller.running)
                port.assert_not_called()
            report = json.loads(next((folder / 'captures').glob('demo_usb/*/result.json')).read_text())
            self.assertEqual(report['status'], 'failed')
            self.assertFalse(report['board_accessed'])
            self.assertIn('public key mismatch', report['error']['message'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
