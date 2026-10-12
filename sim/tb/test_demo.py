"""Offline demo control, authenticated recording and replay; hardware access forbidden."""
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tempfile
import threading
import time
import unittest
import imageio_ffmpeg
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pc/src/host'))
from PIL import Image
from demo_controller import DemoController
from demo_offline import OfflineBoard
from demo_export import ExportCancelled, _run, export_recording
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
                closed = self.wait(controller, lambda kind, data: kind == 'recording' and not data['active'])
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
            self.assertEqual(closed['frames'], len(saved))
            self.assertGreaterEqual(len(saved), 3)
            self.assertEqual(len({row['session_id'] for row, _ in saved}), 2)
            for _, jpeg in saved:
                with Image.open(BytesIO(jpeg)) as image:
                    image.load()
                    self.assertEqual(image.size, (640, 480))

    def test_five_second_offline_live_recording_throughput_pressure(self):
        with tempfile.TemporaryDirectory(prefix='eyepqc-demo-pressure-') as out, \
             patch('demo_controller.Kem', return_value=self.kem), \
             patch('demo_controller.port', side_effect=AssertionError('hardware port access')), \
             patch('demo_controller.serial.Serial', side_effect=AssertionError('serial access')), \
             patch('demo_controller.verify_build', side_effect=AssertionError('firmware access')):
            controller = DemoController('missing-workspace', offline=True, output=out, offline_fps=47)
            controller.start()
            try:
                self.wait(controller, lambda kind, data: kind == 'state' and data['name'] == 'STREAMING')
                controller.request('record_start')
                recording = self.wait(controller, lambda kind, data:
                                      kind == 'recording' and data['active'])['path']
                time.sleep(5.2)
            finally:
                controller.stop()
                controller.thread.join(timeout=10)
            self.assertFalse(controller.running)
            count, first, last = 0, None, None
            for row, jpeg in recording_frames(recording):
                with Image.open(BytesIO(jpeg)) as image:
                    image.load()
                    self.assertEqual(image.size, (640, 480))
                first = row['elapsed'] if first is None else first
                last = row['elapsed']
                count += 1
            fps = (count - 1) / (last - first)
            print(f'SOFTWARE_RECORDING_PRESSURE frames={count} elapsed_s={last - first:.3f} fps={fps:.2f} board_accessed=False')
            self.assertGreaterEqual(count, 150)
            self.assertGreaterEqual(fps, 30)

    def test_ten_second_pregenerated_jpeg_recording_layer_47fps_pressure(self):
        with tempfile.TemporaryDirectory(prefix='eyepqc-recorder-pressure-') as out:
            image = Image.new('RGB', (640, 480), (29, 71, 112))
            data = BytesIO()
            image.save(data, format='JPEG', quality=80)
            jpeg = data.getvalue()
            recorder = FrameRecording(Path(out) / 'recording', {'mode': 'synthetic_pre_generated_frame'})
            started = time.monotonic()
            deadline = started
            frame_id = 0
            try:
                while time.monotonic() - started < 10:
                    delay = deadline - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    header = packet_header(1, frame_id, len(jpeg), 0,
                                           frame_id * 1_000_000 // 47, frame_id)
                    recorder.write(jpeg, header)
                    frame_id += 1
                    deadline += 1 / 47
            finally:
                recorder.close()
            elapsed = time.monotonic() - started
            count, verified = 0, 0
            for row, saved in recording_frames(recorder.folder):
                self.assertEqual(saved, jpeg)
                self.assertAlmostEqual(row['elapsed'], count / 47, delta=.05)
                count += 1
                verified += len(saved)
            fps = count / elapsed
            print(f'RECORDER_LAYER_PRESSURE frames={count} elapsed_s={elapsed:.3f} fps={fps:.2f} '
                  f'verified_bytes={verified} source=synthetic_pre_generated_jpeg')
            self.assertGreaterEqual(count, 460)
            self.assertGreaterEqual(fps, 45)

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

    def test_recording_uses_camera_time_when_transport_delivers_bursts(self):
        with tempfile.TemporaryDirectory() as out:
            recorder = FrameRecording(Path(out) / 'recording', {'mode': 'camera_clock_test'})
            jpeg = Image.new('RGB', (8, 8), (40, 50, 60))
            encoded = BytesIO()
            jpeg.save(encoded, format='JPEG')
            payload = encoded.getvalue()
            for frame_id in range(5):
                header = packet_header(11, frame_id, len(payload), 0,
                                       frame_id * 21276, frame_id)
                recorder.write(payload, header)
            time.sleep(.12)
            for frame_id in range(5):
                header = packet_header(12, frame_id, len(payload), 0,
                                       5000 + frame_id * 21276, frame_id)
                recorder.write(payload, header)
            recorder.close()
            rows = [row for row, _ in recording_frames(recorder.folder)]
            first_span = rows[4]['elapsed'] - rows[0]['elapsed']
            across_rekey = rows[5]['elapsed'] - rows[4]['elapsed']
            second_span = rows[9]['elapsed'] - rows[5]['elapsed']
            self.assertAlmostEqual(first_span, 4 * .021276, delta=.001)
            self.assertGreaterEqual(across_rekey, .015)
            self.assertAlmostEqual(second_span, 4 * .021276, delta=.001)

    def test_recording_rejects_same_session_timestamp_wrap_but_allows_rekey_reset(self):
        with tempfile.TemporaryDirectory() as out:
            recorder = FrameRecording(Path(out) / 'recording', {'mode': 'timestamp_boundary_test'})
            payload = b'jpeg'
            recorder.write(payload, packet_header(21, 0, len(payload), 0, (1 << 64) - 2, 0))
            recorder.write(payload, packet_header(21, 1, len(payload), 0, (1 << 64) - 1, 1))
            with self.assertRaisesRegex(ValueError, 'camera timestamp must increase'):
                recorder.write(payload, packet_header(21, 2, len(payload), 0, 1, 2))
            recorder.write(payload, packet_header(22, 0, len(payload), 0, 1, 0))
            recorder.close()
            rows = [row for row, _ in recording_frames(recorder.folder)]
            self.assertEqual([row['session_id'] for row in rows], [21, 21, 22])
            self.assertTrue(all(left['elapsed'] <= right['elapsed']
                                for left, right in zip(rows, rows[1:])))

    def test_mp4_and_avi_export_decode_every_high_rate_vfr_frame(self):
        with tempfile.TemporaryDirectory() as out:
            recorder = FrameRecording(Path(out) / 'recording', {'mode': 'offline_test'})
            count = 52
            elapsed = 0.0
            for frame_id in range(count):
                if frame_id:
                    elapsed += 1 / 47
                if frame_id == 20:
                    elapsed += .17
                recorder.started = time.monotonic() - elapsed
                image = Image.new('RGB', (64, 48), (frame_id * 4 % 255, 80, 120))
                data = BytesIO()
                image.save(data, format='JPEG', quality=85)
                jpeg = data.getvalue()
                recorder.write(jpeg, packet_header(1, frame_id, len(jpeg), 0,
                                                   frame_id * 21276, frame_id))
            recorder.close()
            source_times = [row['elapsed'] for row, _ in recording_frames(recorder.folder)]
            for container in ('mp4', 'avi'):
                target = Path(out) / f'authenticated.{container}'
                export_recording(recorder.folder, target, container)
                self.assertGreater(target.stat().st_size, 1000)
                decoded = subprocess.run(
                    [imageio_ffmpeg.get_ffmpeg_exe(), '-hide_banner', '-i', str(target),
                     '-vf', 'showinfo', '-f', 'null', '-'], capture_output=True, text=True, check=True)
                pts = [float(value) for value in re.findall(r'pts_time:([0-9.]+)', decoded.stderr)]
                self.assertEqual(len(pts), count)
                self.assertAlmostEqual(pts[1] - pts[0], source_times[1] - source_times[0], delta=.003,
                                       msg=f'{container} timestamps: {pts[:4]}')
                self.assertAlmostEqual(pts[20] - pts[19], source_times[20] - source_times[19], delta=.003)
                self.assertAlmostEqual(pts[-1] - pts[0], source_times[-1] - source_times[0], delta=.003)
                with self.assertRaises(FileExistsError):
                    export_recording(recorder.folder, target, container)
            cancelled = Path(out) / 'cancelled.mp4'
            event = threading.Event()
            event.set()
            with self.assertRaises(ExportCancelled):
                export_recording(recorder.folder, cancelled, 'mp4', event)
            self.assertFalse(cancelled.exists())

    def test_export_rejects_hash_valid_non_jpeg_and_empty_recording(self):
        with tempfile.TemporaryDirectory() as out:
            header = packet_header(1, 0, 4, 0, 1, 0)
            recorder = FrameRecording(Path(out) / 'bad', {'mode': 'test'})
            recorder.write(b'not-a-jpeg', header)
            recorder.close()
            with self.assertRaisesRegex(ValueError, 'JPEG'):
                export_recording(recorder.folder, Path(out) / 'bad.mp4', 'mp4')
            self.assertFalse((Path(out) / 'bad.mp4').exists())
            empty = FrameRecording(Path(out) / 'empty', {'mode': 'test'})
            empty.close()
            with self.assertRaises(ValueError):
                export_recording(empty.folder, Path(out) / 'empty.avi', 'avi')

    def test_export_cancel_terminates_encoder_process(self):
        with tempfile.TemporaryDirectory() as out:
            cancel = threading.Event()
            errors = []
            def run_encoder():
                try:
                    _run([sys.executable, '-c', 'import time; time.sleep(30)'], cancel,
                         Path(out) / 'encoder.log')
                except Exception as exc:
                    errors.append(exc)
            worker = threading.Thread(target=run_encoder)
            worker.start()
            time.sleep(.25)
            cancel.set()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], ExportCancelled)

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
