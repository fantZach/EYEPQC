"""Desktop-only Tk smoke check using an offline peer; no board access."""
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from PIL import ImageGrab

root_path = Path(__file__).resolve().parents[1]
(root_path / 'build').mkdir(exist_ok=True)
sys.path.insert(0, str(root_path / 'src/host'))
from demo_controller import DemoController
from demo_window import DemoWindow, enable_windows_dpi

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
    window.stop_button.invoke()
    wait(lambda: not controller.running)
    root.update()
    # The current run is the most recent one.
    recording = max((root_path / 'data/captures/demo_offline').glob('*/recordings/*/recording.json'), key=lambda p: p.stat().st_mtime)
    window.start_replay(recording.parent)
    wait(lambda: window.status.get() == '录像回放结束', timeout=10)
    assert not errors
    result = dict(status='PASS', board_accessed=False,
                  checks=['Tk button state and counters', 'Tag rejection', 'rekey', 'recording', 'timed replay', 'no Tk callback errors'],
                  screenshot='build/demo_preview.png',
                  recording=str(recording.parent.relative_to(root_path)))
    (root_path / 'build/demo_gui_result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('DEMO_GUI_OK', screenshot)
finally:
    controller.stop()
    if controller.thread:
        controller.thread.join(timeout=5)
    window.end_replay()
    root.destroy()
