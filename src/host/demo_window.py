"""G6 dashboard with software-only preview, authenticated recording and replay."""
import argparse
import ctypes
from io import BytesIO
import os
from pathlib import Path
import time
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import Image, ImageTk
from demo_controller import DemoController
from demo_recording import recording_frames
from g6_board import ROOT


def enable_windows_dpi():
    if os.name == 'nt':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


class DemoWindow:
    def __init__(self, root, controller):
        self.root, self.controller = root, controller
        self.recording = False
        self.replay = None
        self.replay_job = None
        self.pending_replay = None
        self.closing = False
        self.mode = '离线演示 · 合成画面 / 软件密码运算' if controller.offline else '实机演示 · 复用已启动的 G6 固件'
        root.title('EYEPQC · 认证视频演示')
        root.geometry('1080x740')
        root.minsize(1020, 710)
        root.configure(bg='#edf2f7')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background='#edf2f7')
        style.configure('TLabel', background='#edf2f7', font=('Microsoft YaHei UI', -14))
        style.configure('TButton', font=('Microsoft YaHei UI', -14), padding=4)
        shell = ttk.Frame(root, padding=22)
        shell.pack(fill='both', expand=True)
        ttk.Label(shell, text='EYEPQC 认证视频', font=('Microsoft YaHei UI', -28, 'bold')).pack(anchor='w')
        ttk.Label(shell, text=self.mode, foreground='#426579').pack(anchor='w', pady=(3, 16))
        body = ttk.Frame(shell)
        body.pack(fill='both', expand=True)
        video_box = tk.Frame(body, bg='#172235', width=640, height=480)
        video_box.pack(side='left', anchor='n')
        video_box.pack_propagate(False)
        self.image = tk.Label(video_box, text='等待连接', bg='#172235', fg='#b4c8d9',
                              font=('Microsoft YaHei UI', -20))
        self.image.pack(fill='both', expand=True)
        side = ttk.Frame(body, padding=(20, 0, 0, 0))
        side.pack(side='left', fill='both', expand=True)
        self.status = tk.StringVar(value='未连接')
        ttk.Label(side, textvariable=self.status, font=('Microsoft YaHei UI', -18, 'bold'),
                  wraplength=280).pack(anchor='w', pady=(0, 12))
        self.values = {}
        for name in ('会话 ID', '已认证帧', '帧率', '认证失败', '重放拒绝', '丢帧', '换钥次数', '握手耗时'):
            row = ttk.Frame(side)
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=name, foreground='#64748b').pack(side='left')
            value = tk.StringVar(value='—')
            self.values[name] = value
            ttk.Label(row, textvariable=value).pack(side='right')
        self.connect = ttk.Button(side, text='连接', command=self.start)
        self.connect.pack(fill='x', pady=(16, 5))
        self.stop_button = ttk.Button(side, text='断开', command=self.stop, state='disabled')
        self.stop_button.pack(fill='x', pady=3)
        self.rekey = ttk.Button(side, text='立即换钥', command=lambda: controller.request('rekey'), state='disabled')
        self.rekey.pack(fill='x', pady=3)
        self.tamper = ttk.Button(side, text='篡改一包 Tag（本机）', command=lambda: controller.request('tamper'), state='disabled')
        self.tamper.pack(fill='x', pady=3)
        self.record = ttk.Button(side, text='开始录像', command=self.toggle_record, state='disabled')
        self.record.pack(fill='x', pady=3)
        self.play = ttk.Button(side, text='回放录像目录', command=self.choose_replay)
        self.play.pack(fill='x', pady=3)
        self.note = tk.StringVar(value='ML-KEM-512 / AES-128-GCM · 只有认证成功的完整帧进入显示和录像')
        ttk.Label(shell, textvariable=self.note, wraplength=990).pack(anchor='w', pady=(16, 6))
        self.footer = ttk.Label(shell, text='录像保存认证后的明文 JPEG 和逐帧时间戳。板端 DMA / FIFO 计数：未读取。',
                                foreground='#64748b')
        self.footer.pack(anchor='w')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.poll)

    def start(self):
        self.end_replay()
        if self.controller.start():
            self.image.configure(image='', text='正在连接')
            for value in self.values.values():
                value.set('—')
            self.connect.configure(state='disabled')
            self.stop_button.configure(state='normal')

    def stop(self):
        if self.replay is not None:
            self.end_replay()
        self.controller.stop()
        self.status.set('正在结束连接')
        for button in (self.rekey, self.tamper, self.record, self.stop_button):
            button.configure(state='disabled')

    def toggle_record(self):
        self.controller.request('record_stop' if self.recording else 'record_start')
        self.record.configure(state='disabled')

    def draw(self, jpeg):
        with Image.open(BytesIO(jpeg)) as image:
            image.load()
            image = image.convert('RGB')
            image.thumbnail((640, 480))
            photo = ImageTk.PhotoImage(image, master=self.root)
        self.image.configure(image=photo, text='')
        self.image.image = photo

    def poll(self):
        finished = False
        for kind, data in self.controller.updates():
            if kind == 'frame':
                self.draw(data['jpeg'])
            elif kind == 'stats':
                self.values['会话 ID'].set(str(data['session_id']))
                self.values['已认证帧'].set(str(data['frames']))
                self.values['帧率'].set(f"{data['fps']:.1f} fps")
                self.values['认证失败'].set(str(data['errors'].get('auth_failures', 0)))
                self.values['重放拒绝'].set(str(data['errors'].get('replay_rejects', 0)))
                self.values['丢帧'].set(str(data['errors'].get('dropped_frames', 0)))
                self.values['换钥次数'].set(str(data['sessions'] - 1))
            elif kind == 'state':
                self.status.set(data['message'])
                streaming = data['name'] == 'STREAMING'
                for button in (self.rekey, self.tamper, self.record):
                    button.configure(state='normal' if streaming else 'disabled')
            elif kind == 'session':
                self.values['握手耗时'].set(f"{data['handshake_ms']:.1f} ms")
                if data['key_changed'] is True:
                    self.note.set('已完成新握手，视频密钥已变化。')
            elif kind == 'recording':
                self.recording = data['active']
                self.record.configure(text='停止录像' if self.recording else '开始录像', state='normal')
                self.note.set(('正在录制明文：' if self.recording else '录像已保存：') + data['path'])
            elif kind == 'notice':
                self.note.set(data['message'])
            elif kind == 'finished':
                finished = True
                self.connect.configure(state='normal')
                self.play.configure(state='normal')
                for button in (self.rekey, self.tamper, self.record, self.stop_button):
                    button.configure(state='disabled')
                self.note.set('运行记录：' + data['path'])
        if finished and self.pending_replay is not None:
            folder, self.pending_replay = self.pending_replay, None
            self.start_replay(folder)
        if self.closing and not self.controller.running:
            self.root.destroy()
            return
        self.root.after(50, self.poll)

    def end_replay(self):
        if self.replay_job is not None:
            self.root.after_cancel(self.replay_job)
            self.replay_job = None
        if self.replay is not None:
            self.replay.close()
            self.replay = None

    def choose_replay(self):
        folder = filedialog.askdirectory(title='选择包含 recording.json 的录像目录')
        if folder:
            if self.controller.running:
                self.pending_replay = folder
                self.note.set('已选择录像，正在结束实时会话并准备回放。')
                self.stop()
            else:
                self.start_replay(folder)

    def start_replay(self, folder):
        self.end_replay()
        for value in self.values.values():
            value.set('—')
        self.replay = iter(recording_frames(folder))
        self.replay_origin = None
        self.status.set('录像回放 · 文件一致性校验')
        self.note.set('回放已解密的录像，逐帧校验文件哈希；不代表重新进行 GCM 或实机验收。')
        self.next_replay()

    def next_replay(self):
        try:
            row, jpeg = next(self.replay)
            if self.replay_origin is None:
                self.replay_origin = time.monotonic() - row['elapsed']
            delay = max(0, self.replay_origin + row['elapsed'] - time.monotonic())
            def show():
                try:
                    self.draw(jpeg)
                    self.next_replay()
                except (OSError, ValueError) as exc:
                    self.end_replay()
                    self.status.set('录像解码失败')
                    self.note.set(str(exc))
            self.replay_job = self.root.after(max(1, int(delay * 1000)), show)
        except StopIteration:
            self.end_replay()
            self.status.set('录像回放结束')
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.end_replay()
            self.status.set('录像校验失败')
            self.note.set(str(exc))

    def close(self):
        self.end_replay()
        self.closing = True
        self.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true', help='synthetic/software-only; never accesses hardware')
    parser.add_argument('--workspace', type=Path, default=ROOT / 'build/vitis/usbfix3_20261007')
    args = parser.parse_args()
    enable_windows_dpi()
    root = tk.Tk()
    DemoWindow(root, DemoController(args.workspace, args.offline))
    root.mainloop()


if __name__ == '__main__':
    main()
