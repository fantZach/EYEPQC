"""One transport owner; Tk consumes events and never reads USB itself."""
from collections import Counter
from datetime import datetime
import hashlib
import hmac
import json
from pathlib import Path
import queue
import threading
import time

import serial
from build_manifest import verify as verify_build
from demo_offline import OfflineBoard
from demo_recording import FrameRecording
from g6_board import ROOT, drain_rekey, frames, handshake, port, send_control
from handshake import HostSession
from m09 import Kem, LIB, OUT, build
from protocol import MessageType, UsbRecordDecoder


class DemoController:
    def __init__(self, workspace, offline=False, output=None, offline_fps=20):
        self.workspace = Path(workspace)
        self.offline = offline
        self.output = Path(output or ROOT / 'data/captures')
        self.offline_fps = offline_fps
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest = {}
        self.thread = None

    def emit(self, kind, **data):
        if kind in ('frame', 'stats'):
            with self.lock:
                self.latest[kind] = data
        else:
            self.events.put((kind, data))

    def updates(self):
        with self.lock:
            latest, self.latest = self.latest, {}
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                break
        return result + list(latest.items())

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        if self.running:
            return False
        self.commands = queue.Queue()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name='EYEPQC-demo-receiver', daemon=False)
        self.thread.start()
        return True

    def request(self, command):
        if command not in ('rekey', 'tamper', 'record_start', 'record_stop'):
            raise ValueError('unknown demo command')
        if self.running:
            self.commands.put(command)

    def stop(self):
        self.stop_event.set()

    def _run(self):
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        run = self.output / ('demo_offline' if self.offline else 'demo_usb') / stamp
        try:
            run.mkdir(parents=True)
        except OSError as exc:
            self.emit('state', name='FAILED', message=str(exc))
            self.emit('finished', status='failed', path=str(run))
            return
        report = dict(status='running', offline=self.offline, board_accessed=False,
                      firmware_loaded=False, sessions=[], board_counters=None)
        ser = session = recorder = previous_key = None
        totals = Counter()
        errors = Counter()
        action = None
        tamper = False
        ready = False
        last_stats = {}
        source = dict(mode='offline_synthetic' if self.offline else 'live_usb', build=None)

        def statistics(stats):
            nonlocal last_stats
            last_stats = stats
            current_errors = errors + Counter(stats['errors'])
            self.emit('stats', frames=totals['frames'] + stats['frames'], fps=stats['fps'],
                      bytes=totals['bytes'] + stats['bytes'], errors=dict(current_errors),
                      session_id=stats['session_id'], sessions=len(report['sessions']) + 1)

        def poll():
            nonlocal action, tamper, recorder
            while True:
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    break
                if command == 'rekey':
                    action = 'rekey'
                elif command == 'tamper':
                    tamper = True
                elif command == 'record_start' and recorder is None:
                    folder = run / 'recordings' / datetime.now().strftime('%H%M%S_%f')
                    recorder = FrameRecording(folder, source)
                    self.emit('recording', active=True, path=str(folder))
                elif command == 'record_stop' and recorder is not None:
                    recorder.close()
                    self.emit('recording', active=False, path=str(recorder.folder))
                    recorder = None
            return self.stop_event.is_set() or action == 'rekey'

        def transform(record):
            nonlocal tamper
            if tamper:
                tamper = False
                self.emit('notice', message='已在本机修改一个视频包的 Tag，等待认证拒绝及下一帧恢复。')
                return record[:-1] + bytes([record[-1] ^ 1])
            return record

        def accepted(jpeg, header, stats):
            nonlocal ready
            if recorder is not None:
                recorder.write(jpeg, header)
            statistics(stats)
            self.emit('frame', jpeg=jpeg)
            if stats['frames'] >= 2 and not ready:
                ready = True
                self.emit('state', name='STREAMING', message='认证视频运行中')

        try:
            (run / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            self.emit('state', name='CONNECTING', message='正在准备离线演示' if self.offline else '正在连接视频 CDC')
            if not LIB.is_file():
                build()
            kem = Kem()
            if self.offline:
                ser = OfflineBoard(kem, self.offline_fps)
                pk, pin = ser.pk, hashlib.sha256(ser.pk).digest()
                session = HostSession(pk, pin, kem)
            else:
                manifest, _ = verify_build(self.workspace, 'g6_usb_manifest.json')
                if manifest.get('application') != 'g6_usb':
                    raise ValueError('Expected G6 firmware build')
                source['build'] = report['build'] = dict(
                    manifest_sha256=hashlib.sha256((self.workspace / 'g6_usb_manifest.json').read_bytes()).hexdigest(),
                    elf_sha256=hashlib.sha256((self.workspace / 'g6_usb/build/g6_usb.elf').read_bytes()).hexdigest(),
                    xsa_sha256=manifest['xsa_sha256'])
                pk = (OUT / 'public.bin').read_bytes()
                pin = bytes.fromhex((OUT / 'public.sha256').read_text().strip())
                session = HostSession(pk, pin, kem)
                device = port(10, self.stop_event.is_set)
                ser = serial.Serial(port=None, baudrate=115200, timeout=.25)
                ser.dtr = False
                ser.port = device
                report['port_open_attempted'] = True
                ser.open()
                report['board_accessed'] = True
                ser.reset_input_buffer()
                ser.dtr = True
                report['port'] = device
            decoder = UsbRecordDecoder()
            while not self.stop_event.is_set():
                ready = False
                self.emit('state', name='HANDSHAKE', message='正在验证新会话')
                started = time.perf_counter()
                handshake(ser, decoder, session, cancelled=self.stop_event.is_set)
                current_key = bytearray(session.video_key)
                changed = None if previous_key is None else not hmac.compare_digest(previous_key, current_key)
                if previous_key is not None:
                    previous_key[:] = bytes(len(previous_key))
                previous_key = current_key
                if changed is False:
                    raise RuntimeError('fresh handshake repeated video key')
                self.emit('session', session_id=session.session_id, key_changed=changed,
                          handshake_ms=(time.perf_counter() - started) * 1000)
                result = frames(ser, decoder, session, 86400, run / f"session_{len(report['sessions']) + 1}",
                                on_frame=accepted, on_stats=statistics, should_stop=poll, transform=transform)
                result['key_changed'] = changed
                report['sessions'].append(result)
                totals.update({k: result[k] for k in ('frames', 'bytes')})
                errors.update(result['errors'])
                (run / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
                if self.stop_event.is_set() or action != 'rekey':
                    break
                self.emit('state', name='REKEYING', message='正在排空旧会话并换钥')
                send_control(ser, session.command(MessageType.REKEY))
                drain_rekey(ser, decoder)
                decoder = UsbRecordDecoder()
                action = None
            if session is not None and session.state == 'STREAMING':
                send_control(ser, session.command(MessageType.STOP))
            report['status'] = 'stopped'
        except InterruptedError:
            report['status'] = 'cancelled'
        except Exception as exc:
            report.update(status='failed', error=dict(type=type(exc).__name__, message=str(exc)),
                          last_session_stats=last_stats)
            self.emit('state', name='FAILED', message=str(exc))
        finally:
            try:
                if recorder is not None:
                    recorder.close()
                    self.emit('recording', active=False, path=str(recorder.folder))
            except OSError as exc:
                report.update(status='failed', recording_error=str(exc))
                self.emit('state', name='FAILED', message=str(exc))
            if ser is not None:
                try:
                    if not self.offline:
                        ser.dtr = False
                    ser.close()
                except (serial.SerialException, OSError):
                    pass
            if session is not None:
                session.close()
            if previous_key is not None:
                previous_key[:] = bytes(len(previous_key))
            try:
                (run / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
            except OSError as exc:
                report['status'] = 'failed'
                self.emit('state', name='FAILED', message='无法保存运行记录：' + str(exc))
            self.emit('finished', status=report['status'], path=str(run / 'result.json'))
            if report['status'] != 'failed':
                self.emit('state', name='DISCONNECTED', message='连接已结束')
