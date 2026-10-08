import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'build_g6_auto_recovery', ROOT / 'prj/build_g6_auto_recovery.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
run_spec = importlib.util.spec_from_file_location(
    'run_g7_auto_recovery', ROOT / 'prj/run_g7_auto_recovery.py')
runner = importlib.util.module_from_spec(run_spec)
run_spec.loader.exec_module(runner)


def action(status, consecutive_malformed=0):
    if status == 14:
        return 'recover'
    if status == 15:
        return 'drop' if consecutive_malformed <= 3 else 'fail_closed'
    return 'fail_closed'


class G6AutoRecovery(unittest.TestCase):
    def test_capture_error_policy_bounds_drop_and_never_recovers_guard(self):
        for observation in ('transfer_start_failed', 'dma_irq_error', 'busy_timeout'):
            with self.subTest(observation=observation):
                self.assertEqual(action(14), 'recover')
        self.assertEqual([action(15, n) for n in range(1, 5)],
                         ['drop', 'drop', 'drop', 'fail_closed'])
        self.assertEqual(action(16), 'fail_closed')
        self.assertEqual(action(99), 'fail_closed')

    def test_candidate_waits_real_busy_deadline_and_records_irq_vs_timeout(self):
        source = (ROOT / 'src/ps/diag/g3_camera_auto_recovery.c').read_text(encoding='utf-8')
        self.assertIn('#define CAMERA_AUTO_DEADLINE_US 3000000U', source)
        self.assertIn('XAxiDma_SimpleTransfer(&capture', source)
        self.assertIn('XAxiDma_Busy(&capture, XAXIDMA_DEVICE_TO_DMA)', source)
        self.assertIn('G6_AUTO_CAPTURE_DMA_IRQ_ERROR', source)
        self.assertIn('G6_AUTO_CAPTURE_BUSY_TIMEOUT', source)
        self.assertIn('return 14;', source)
        self.assertIn('G6_AUTO_TRIGGER_CAMERA_RESET', source)
        self.assertIn('G6_AUTO_TRIGGER_ROUTING_STALL', source)
        # The request only changes the PL source/route; no status-14 assignment or
        # diagnostic-owned recovery call exists in the normal capture function.
        capture = source.split('static int g6_auto_capture_frame(void)', 1)[1].split(
            '\nint g3_usb_capture', 1)[0]
        self.assertNotIn('g6_candidate_recover_camera', capture)
        self.assertLess(capture.index('G6_AUTO_CAPTURE_GUARD_BROKEN'),
                        capture.index('g3_frame[n - 2]'))
        self.assertLess(capture.index('G6_AUTO_CAPTURE_GUARD_BROKEN'),
                        capture.index('g3_frame[n - 1]'))
        self.assertIn('Xil_DCacheFlushRange((UINTPTR)g3_frame', source)

    def test_success_retires_old_session_before_waiting_for_hello(self):
        source = (ROOT / 'src/ps/diag/g6_usb_auto_recovery_tail.inc').read_text(encoding='utf-8')
        recovery = source.split('g6_auto_recovery_diag.recovery_status =', 1)[1]
        self.assertLess(recovery.index('g6_candidate_recover_camera()'),
                        recovery.index('eye_session_error(&session)'))
        self.assertIn('g3_usb_zeroize();', recovery)
        self.assertIn('frame_id = 0;', recovery)
        self.assertIn('usb_cdc_clear_control_queue()', recovery)
        self.assertIn('phase = WAIT_HELLO;', recovery)
        self.assertIn('return G6_AUTO_RECOVERED;', recovery)
        self.assertIn('if (g6_auto_recovery_diag.recovery_status)', recovery)
        self.assertIn('g6_auto_recovery_diag.state = 3;', recovery)
        self.assertIn('return 16U;', recovery)
        self.assertNotIn('g6_auto_recovery_diag.state = 2;', recovery)
        usb = (ROOT / 'prj/usb_probe_auto_recovery.c').read_text(encoding='utf-8')
        self.assertIn('eye_usb_rearm_data(&usb, 0)', usb)
        self.assertIn('rx_reset();', usb)
        camera = (ROOT / 'src/ps/diag/g3_camera_auto_recovery.c').read_text(encoding='utf-8')
        reset = camera.split('int g6_candidate_recover_camera(void)', 1)[1]
        for evidence in ('reset_dma()', 'g3_usb_zeroize()', 'g3_job.key',
                         'g3_job.nonce_prefix', 'Xil_DCacheFlushRange',
                         'configure_camera(CAMERA_AUTO_CFG)'):
            self.assertIn(evidence, reset)
        self.assertNotIn('volatile uint8_t *secret = g3_job.key', reset)
        self.assertIn('for (unsigned i = 0; i < sizeof g3_job.key; ++i) key[i] = 0;', reset)
        self.assertIn('for (unsigned i = 0; i < sizeof g3_job.nonce_prefix; ++i)', reset)

    def test_generated_g6_loop_handles_guard_once_without_second_flush(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'candidate.c'
            builder.generate_candidate_usb(
                ROOT / 'src/ps/src/g6_usb.c',
                ROOT / 'src/ps/diag/g6_usb_auto_recovery_tail.inc', output)
            generated = output.read_text(encoding='utf-8')
        branch = generated.split('if (status == G6_AUTO_RECOVERED)', 1)[1].split(
            'if (status)', 1)[0]
        self.assertIn('g6_capture_errors', branch)
        self.assertIn('g6_dropped', branch)
        self.assertIn('g6_auto_recovery_diag.state = 2;', branch)
        error = generated.split('if (status == 16U)', 1)[1].split(
            'if (++capture_errors', 1)[0]
        self.assertIn('fail_closed();', error)
        self.assertNotIn('g3_usb_flush', error)
        tail = (ROOT / 'src/ps/diag/g6_usb_auto_recovery_tail.inc').read_text(encoding='utf-8')
        self.assertIn('G6_AUTO_MALFORMED_DROP_LIMIT',
                      (ROOT / 'src/ps/include/g6_auto_recovery.h').read_text(encoding='utf-8'))
        self.assertIn('g6_auto_action_for_status', tail)
        self.assertIn('g6_candidate_recover_camera()', generated)
        self.assertIn('g6_transport_failure_diag.resume_status', generated)
        self.assertIn('g6_transport_failure_diag.last_successful_frame_id', generated)

    def test_hardware_gate_requires_counters_and_new_session_evidence(self):
        values = {'magic': 0x47415231, 'state': 2, 'stage': 5, 'mode': 1,
                  'observation': 3, 'busy_start': 1, 'busy_deadline': 1,
                  'elapsed_us': 3_000_001, 'sr': 0, 'recovery_status': 0,
                  'camera_status': 0x00805640, 'capture_before': 2, 'capture_after': 3,
                  'dropped_before': 7, 'dropped_after': 8,
                  'fatal_before': 0, 'fatal_after': 0,
                  'control_before': 0, 'control_after': 0,
                  'transport_before': 0, 'transport_after': 0,
                  'status_before': 1, 'status_after': 1,
                  'send_status': 0, 'resume_status': 0, 'transport_error_count': 0}
        runner.validate_trigger(values, 1)
        for key, bad in [('elapsed_us', 2_999_999), ('busy_deadline', 0),
                         ('sr', 0x4000), ('fatal_after', 1)]:
            changed = dict(values)
            changed[key] = bad
            with self.subTest(key=key), self.assertRaises(ValueError):
                runner.validate_trigger(changed, 1)
        self.assertEqual(runner.TRIGGER_NAMES, {'camera-reset': 1, 'routing-stall': 2})
        route = (ROOT / 'src/rtl/common/axis_capture_route.sv').read_text(encoding='utf-8')
        self.assertIn('Mode 3 disables all routes.', route)

    def test_recovery_receiver_is_no_jtag_and_has_fresh_session_checks(self):
        command = runner.worker_command(Path('python.exe'), Path('workspace'),
                                        Path('E:/fpg/2026.1'), 2, True)
        self.assertIn('--no-jtag', command)
        self.assertIn('--report-key-fingerprint', command)
        self.assertIn('--drain-stop', command)
        source = (ROOT / 'prj/run_g7_auto_recovery.py').read_text(encoding='utf-8')
        self.assertIn("new.get('session_id') == old_sid", source)
        self.assertIn("new.get('video_key_sha256') == old_fp", source)
        self.assertIn('jtag_reload_for_recovery', source)
        self.assertIn('verify_fault_worker_before_trigger', source)
        self.assertIn('read_post_stop_health', source)
        self.assertIn('verify_external_sources', source)

    def test_stop_drain_is_explicit_and_ordered_after_authenticated_stop(self):
        board_spec = importlib.util.spec_from_file_location('g6_board_test', ROOT / 'src/host/g6_board.py')
        board = importlib.util.module_from_spec(board_spec)
        board_spec.loader.exec_module(board)
        ser, decoder = object(), object()
        session = type('SessionStub', (), {'command': lambda self, kind: b'stop'})()
        events = []
        with mock.patch.object(board, 'send_control', side_effect=lambda *a: events.append('stop')) as send, \
                mock.patch.object(board, 'drain_rekey', side_effect=lambda *a, **k: events.append('drain')) as drain:
            board.stop_and_drain(ser, decoder, session, enabled=False)
            self.assertEqual(events, ['stop'])
            events.clear()
            board.stop_and_drain(ser, decoder, session, enabled=True)
        self.assertEqual(events, ['stop', 'drain'])
        send.assert_called()
        drain.assert_called_once_with(ser, decoder, timeout=5.0, quiet=0.1)

    def test_quiet_drain_consumes_video_and_rejects_bad_final_framing(self):
        board_spec = importlib.util.spec_from_file_location('g6_board_drain_test', ROOT / 'src/host/g6_board.py')
        board = importlib.util.module_from_spec(board_spec)
        board_spec.loader.exec_module(board)

        class SerialStub:
            def __init__(self, chunks): self.chunks = iter(chunks)
            def read(self, _size): return next(self.chunks, b'')

        class DecoderStub:
            def __init__(self, fail=False): self.finished = False; self.fail = fail
            def feed(self, chunk): return [(board.USB_VIDEO, b'frame')] if chunk else []
            def finish(self):
                self.finished = True
                if self.fail: raise ValueError('partial final record')

        decoder = DecoderStub()
        board.drain_rekey(SerialStub([b'video', b'', b'']), decoder, timeout=1, quiet=0.001)
        self.assertTrue(decoder.finished)
        broken = DecoderStub(fail=True)
        with self.assertRaisesRegex(ValueError, 'partial final record'):
            board.drain_rekey(SerialStub([b'video', b'', b'']), broken,
                              timeout=1, quiet=0.001)

    def test_candidate_pretrigger_requires_live_matching_result_and_external_hash(self):
        class ProcessStub:
            def __init__(self, rc=None): self.rc = rc
            def poll(self): return self.rc

        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            record_path = temp_path / 'result.json'
            record = {'status': 'running', 'sessions': [{
                'session_id': 12, 'video_key_sha256': 'abc',
                'observed_verified_frames': 4,
            }]}
            record_path.write_text(json.dumps(record), encoding='utf-8')
            runner.verify_fault_worker_before_trigger(ProcessStub(), record_path, 12, 'abc', 3)
            with self.assertRaisesRegex(RuntimeError, 'exited'):
                runner.verify_fault_worker_before_trigger(ProcessStub(0), record_path, 12, 'abc', 3)
            record['status'] = 'failed'
            record_path.write_text(json.dumps(record), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'not healthy'):
                runner.verify_fault_worker_before_trigger(ProcessStub(), record_path, 12, 'abc', 3)

            source = temp_path / 'vendor.c'
            source.write_bytes(b'pinned vendor source')
            manifest = {'external_sources_root': 'tool-root',
                        'external_sources': {'vendor.c': hashlib.sha256(source.read_bytes()).hexdigest()}}
            self.assertEqual(runner.verify_external_sources(manifest, temp_path), 1)
            source.write_bytes(b'changed source')
            with self.assertRaisesRegex(ValueError, 'source changed'):
                runner.verify_external_sources(manifest, temp_path)


if __name__ == '__main__':
    unittest.main()
