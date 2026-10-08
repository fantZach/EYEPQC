"""Desktop-only Tk smoke check using an offline peer; no board access."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import tkinter as tk
from PIL import ImageGrab
from unittest.mock import patch

root_path = Path(__file__).resolve().parents[1]
(root_path / 'build').mkdir(exist_ok=True)
sys.path.insert(0, str(root_path / 'src/host'))
from demo_controller import DemoController
from demo_window import DemoWindow, enable_windows_dpi
from demo_recording import recording_frames

enable_windows_dpi()
root = tk.Tk()
root.geometry('1080x740+40+40')
controller = DemoController('missing-workspace', offline=True)
window = DemoWindow(root, controller)
errors = []
root.report_callback_exception = lambda cls, value, trace: errors.append(str(value))

def wait(predicate, timeout=5):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        root.update()
        if errors:
            raise AssertionError(errors)
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('GUI condition timeout: ' + window.status.get())

try:
    window.connect.invoke()
    wait(lambda: window.status.get() == '认证视频运行中')
    with patch('demo_window.filedialog.askdirectory', return_value=''):
        window.play.invoke()
    wait(lambda: window.status.get() == '认证视频运行中')
    window.record.invoke()
    wait(lambda: window.recording)
    wait(lambda: int(window.values['已认证帧'].get()) >= 5)
    window.tamper.invoke()
    wait(lambda: window.values['认证失败'].get() == '1')
    window.rekey.invoke()
    wait(lambda: window.values['换钥次数'].get() == '1' and window.status.get() == '认证视频运行中')
    root.lift()
    root.attributes('-topmost', True)
    root.update()
    assert window.footer.winfo_rooty() + window.footer.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    bbox = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(),
            root.winfo_rooty() + root.winfo_height())
    screenshot = root_path / 'build/demo_preview.png'
    ImageGrab.grab(bbox=bbox).save(screenshot)
    root.attributes('-topmost', False)
    window.record.invoke()
    wait(lambda: not window.recording)
    recording = Path(window.last_recording_folder)
    assert window.last_recorded_frame_count == sum(1 for _ in recording_frames(recording))
    with patch.object(controller, 'stop', side_effect=OSError('simulated stop failure')):
        with patch('demo_window.filedialog.askdirectory', return_value=str(recording)):
            window.choose_replay()
    assert controller.running and window.pending_replay is None
    with patch('demo_window.filedialog.askdirectory', return_value=str(recording)):
        window.choose_replay()
    wait(lambda: not controller.running and window.status.get() == '录像回放结束', timeout=10)
    assert window.last_recording_folder == str(recording)
    with tempfile.TemporaryDirectory(prefix='eyepqc-gui-export-') as exports:
        mp4, avi = Path(exports) / 'gui.mp4', Path(exports) / 'gui.avi'
        with patch('demo_window.filedialog.asksaveasfilename', return_value=str(mp4)):
            window.export_mp4.invoke()
        wait(lambda: window.export_thread is None and '导出完成' in window.note.get(), timeout=30)
        assert mp4.is_file()
        with patch('demo_window.filedialog.asksaveasfilename', return_value=str(avi)):
            window.export_avi.invoke()
        wait(lambda: window.export_thread is None and '导出完成' in window.note.get(), timeout=30)
        assert avi.is_file()
        bad_recording = Path(exports) / 'tampered-recording'
        shutil.copytree(recording, bad_recording)
        first_frame = next(bad_recording.glob('*.jpg'))
        first_frame.write_bytes(b'corrupt')
        window.start_replay(bad_recording)
        wait(lambda: window.status.get() == '录像校验失败')
    assert not errors
    result = dict(status='PASS', board_accessed=False,
                  checks=['Tk button state and counters', 'cancelled file picker preserves live session',
                          'Tag rejection', 'rekey', 'recording', 'live-to-replay stop flow',
                          'simulated stop failure', 'timed replay', 'MP4 and AVI GUI exports',
                          'tampered recording rejection', 'no Tk callback errors'],
                  screenshot='build/demo_preview.png',
                  recording=str(recording.relative_to(root_path)))
    (root_path / 'build/demo_gui_result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('DEMO_GUI_OK', screenshot)
finally:
    controller.stop()
    if controller.thread:
        controller.thread.join(timeout=5)
    window.end_replay()
    root.destroy()
