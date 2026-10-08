"""Opt-in live G6 GUI recording acceptance; opens USB but never invokes JTAG."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import time
import tkinter as tk
from unittest.mock import patch

root_path = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_path / 'src/host'))
from demo_controller import DemoController
from demo_window import DemoWindow, enable_windows_dpi
from demo_recording import recording_frames
from g6_board import ROOT


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=ROOT / 'build/vitis/usbfix3_20261007')
    parser.add_argument('--record-seconds', type=float, default=15,
                        help='live recording duration, from 10 to 30 seconds')
    parser.add_argument('--offline-smoke', action='store_true',
                        help='exercise the same GUI sequence with synthetic software video; no USB access')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'data/captures/demo_live_acceptance')
    args = parser.parse_args()
    if not 10 <= args.record_seconds <= 30:
        parser.error('--record-seconds must be between 10 and 30')
    return args


def main():
    args = parse_args()
    run = args.output / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    run.mkdir(parents=True, exist_ok=False)
    result_path = run / 'result.json'
    result = dict(status='running', board_accessed=False, jtag_accessed=False,
                  workspace=str(args.workspace), record_seconds=args.record_seconds,
                  offline_smoke=args.offline_smoke,
                  stages=[])
    root = None
    controller = None
    window = None
    stage = 'initialize'
    errors = []

    def persist():
        result['updated_at'] = datetime.now().astimezone().isoformat()
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def begin_stage(name):
        nonlocal stage
        stage = name
        result['active_stage'] = name
        persist()

    def finish_stage(name):
        result['last_completed_stage'] = name
        result['stages'].append(name)
        persist()

    try:
        persist()
        enable_windows_dpi()
        root = tk.Tk()
        root.geometry('1080x740+40+40')
        controller = DemoController(args.workspace, offline=args.offline_smoke, output=run / 'captures')
        window = DemoWindow(root, controller)
        root.report_callback_exception = lambda cls, value, trace: errors.append(str(value))

        def wait(predicate, timeout=30, allow_receiver_stopped=False):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                root.update()
                if errors:
                    raise RuntimeError('Tk callback error: ' + '; '.join(errors))
                if predicate():
                    return
                if (not allow_receiver_stopped and controller.thread is not None and
                        controller.thread.ident is not None and not controller.running):
                    raise RuntimeError('live receiver exited: ' + window.status.get())
                time.sleep(.01)
            raise TimeoutError('timeout at stage ' + stage + ': ' + window.status.get())

        begin_stage('connect-live-g6')
        window.connect.invoke()
        wait(lambda: window.status.get() == '认证视频运行中', timeout=90)
        finish_stage(stage)

        begin_stage('start-authenticated-recording')
        window.record.invoke()
        wait(lambda: window.recording)
        recording = Path(window.last_recording_folder)
        wait(lambda: int(window.values['已认证帧'].get()) >= 5)
        finish_stage(stage)

        begin_stage('tag-rejection-and-recovery')
        window.tamper.invoke()
        wait(lambda: int(window.values['认证失败'].get()) >= 1)
        wait(lambda: int(window.values['已认证帧'].get()) >= 7)
        finish_stage(stage)

        begin_stage('authenticated-rekey-during-recording')
        window.rekey.invoke()
        wait(lambda: int(window.values['换钥次数'].get()) >= 1 and
             window.status.get() == '认证视频运行中', timeout=90)
        post_rekey_session_id = int(window.values['会话 ID'].get())
        post_rekey_started = time.monotonic()
        finish_stage(stage)

        begin_stage('recording-duration')
        until = time.monotonic() + args.record_seconds
        while time.monotonic() < until:
            root.update()
            if errors:
                raise RuntimeError('Tk callback error: ' + '; '.join(errors))
            if not controller.running:
                raise RuntimeError('live receiver stopped during recording')
            time.sleep(.01)
        window.record.invoke()
        wait(lambda: not window.recording)
        count, first, last = 0, None, None
        for row, _ in recording_frames(recording):
            first = row['elapsed'] if first is None else first
            last = row['elapsed']
            count += 1
        if count < 2:
            raise RuntimeError(f'live recording produced only {count} frames')
        result.update(recording=str(recording), recording_frames=count,
                      recording_seconds=last - first,
                      recording_fps=(count - 1) / (last - first),
                      recorder_callback_frames=window.last_recorded_frame_count)
        post_rekey_count, post_rekey_first, post_rekey_last = 0, None, None
        for row, _ in recording_frames(recording):
            if row['session_id'] == post_rekey_session_id:
                post_rekey_first = row['elapsed'] if post_rekey_first is None else post_rekey_first
                post_rekey_last = row['elapsed']
                post_rekey_count += 1
        if post_rekey_count < 2:
            raise RuntimeError('not enough recorded frames after rekey to measure continuous capture')
        result['post_rekey_recording'] = dict(
            session_id=post_rekey_session_id,
            frames=post_rekey_count,
            elapsed_s=post_rekey_last - post_rekey_first,
            fps=(post_rekey_count - 1) / (post_rekey_last - post_rekey_first),
            wall_seconds=time.monotonic() - post_rekey_started)
        if count != window.last_recorded_frame_count:
            raise RuntimeError('saved frame count differs from authenticated recorder callback count')
        finish_stage(stage)

        begin_stage('choose-replay-while-live-stop-and-replay')
        with patch('demo_window.filedialog.askdirectory', return_value=str(recording)):
            window.play.invoke()
        wait(lambda: not controller.running and window.status.get() == '录像回放结束',
             timeout=90, allow_receiver_stopped=True)
        if window.last_run_status != 'stopped':
            raise RuntimeError(f'live session ended with status {window.last_run_status!r}')
        finish_stage(stage)

        begin_stage('reconnect-after-replay')
        window.connect.invoke()
        wait(lambda: window.status.get() == '认证视频运行中', timeout=90)
        finish_stage(stage)

        begin_stage('export-and-decode-mp4-avi')
        exports = run / 'exports'
        exports.mkdir()
        mp4, avi = exports / 'live.mp4', exports / 'live.avi'
        def wait_for_export():
            wait(lambda: window.export_thread is None and
                 ('导出完成' in window.note.get() or '导出失败' in window.note.get() or
                  '导出已取消' in window.note.get()), timeout=120)
            if '导出完成' not in window.note.get():
                raise RuntimeError(window.note.get())
        with patch('demo_window.filedialog.asksaveasfilename', return_value=str(mp4)):
            window.export_mp4.invoke()
        wait_for_export()
        with patch('demo_window.filedialog.asksaveasfilename', return_value=str(avi)):
            window.export_avi.invoke()
        wait_for_export()
        result['mp4_bytes'] = mp4.stat().st_size
        result['avi_bytes'] = avi.stat().st_size
        finish_stage(stage)
        result['status'] = 'passed'
        result['board_accessed'] = not args.offline_smoke
        result['recording_exported_frame_count'] = count
    except Exception as exc:
        result.update(status='failed', failed_stage=stage,
                      error=dict(type=type(exc).__name__, message=str(exc)),
                      board_accessed=bool(controller and controller.running))
        if window is not None:
            result['last_ui_stats'] = {name: value.get() for name, value in window.values.items()}
            result['last_ui_status'] = window.status.get()
        persist()
    finally:
        if window is not None:
            if window.export_cancel is not None:
                window.export_cancel.set()
            window.end_replay()
            if window.export_thread is not None:
                window.export_thread.join(timeout=30)
                if window.export_thread.is_alive():
                    result.update(status='failed', failed_stage='export-cleanup',
                                  error=dict(type='TimeoutError', message='export thread did not stop'))
        if controller is not None:
            controller.stop()
            if controller.thread:
                controller.thread.join(timeout=10)
            category = 'demo_offline' if args.offline_smoke else 'demo_usb'
            reports = sorted((run / 'captures' / category).glob('*/result.json'),
                             key=lambda item: item.stat().st_mtime)
            if reports:
                controller_runs = []
                try:
                    for live_report_path in reports:
                        live_report = json.loads(live_report_path.read_text(encoding='utf-8'))
                        controller_runs.append(dict(
                            status=live_report.get('status'),
                            board_accessed=bool(live_report.get('board_accessed')),
                            port_open_attempted=bool(live_report.get('port_open_attempted')),
                            sessions=live_report.get('sessions', []),
                            result=str(live_report_path)))
                        result['board_accessed'] = (result.get('board_accessed', False) or
                                                    bool(live_report.get('board_accessed')))
                except (OSError, ValueError):
                    result['controller_report_error'] = 'could not read controller result'
                result['controller_runs'] = controller_runs
                result['controller_sessions'] = [session for live_run in controller_runs
                                                 for session in live_run['sessions']]
        if root is not None:
            root.destroy()
        result['tk_errors'] = errors
        persist()
        print('DEMO_LIVE_ACCEPTANCE', result['status'], result_path)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
