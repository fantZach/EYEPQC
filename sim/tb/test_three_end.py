"""Android Java/OkHttp -> real loopback WS bridge -> C board session/ML-KEM.

Synthetic JPEG and simulated USB/DMA only; no physical board or Android device.
Run mobile/test.ps1 first to compile the Java test adapter.
"""
import asyncio
import ctypes as ct
import hashlib
from io import BytesIO
import os
import shutil
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'pc/src/host'), str(ROOT / 'sim/tb')]
from PIL import Image
from relay import Relay
import test_g6 as reference
from test_m10 import array
from protocol import decode_control, USB_CONTROL, UsbRecordDecoder


class SimulatedCdc:
    def __init__(self):
        self.board = reference.MemoryBoard(reference.G6.lib, reference.G6.kem,
                                           reference.G6.pk, reference.G6.sk)
        self.commands = []
        self.closed = False
        self._dtr = False

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = value
        if not value:
            self.board.pending.clear()
            reference.G6.lib.eye_session_init(ct.byref(self.board.session), array(reference.G6.pk))

    def read(self, size):
        return self.board.read(size)

    def write(self, record):
        channel, message = UsbRecordDecoder().feed(record)[0]
        assert channel == USB_CONTROL
        self.commands.append(decode_control(message)[0])
        return self.board.write(record)

    def reset_input_buffer(self):
        self.board.pending.clear()

    def reset_output_buffer(self):
        pass

    def close(self):
        self.closed = True


class ThreeEnd(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        reference.G6.setUpClass()

    @classmethod
    def tearDownClass(cls):
        reference.G6.tearDownClass()

    async def test_android_okhttp_handshake_video_and_reconnect(self):
        java = Path(os.environ['JAVA_HOME']) / 'bin/java.exe' if os.environ.get('JAVA_HOME') else Path(shutil.which('java') or 'java')
        tools = ROOT / 'build/mobile_toolchain'
        classpath = os.pathsep.join(str(tools / name) for name in
            ('classes', 'bcprov.jar', 'okhttp.jar', 'okio.jar', 'kotlin.jar'))
        self.assertTrue(java.is_file(), 'Set JAVA_HOME to a JDK; run mobile/test.ps1')
        self.assertTrue((tools / 'classes/org/eyepqc/mobile/NetworkCli.class').is_file(),
                        'Run mobile/test.ps1 to compile the Java adapter')
        image = BytesIO()
        Image.new('RGB', (640, 480), (0, 120, 180)).save(image, format='JPEG')
        expected = hashlib.sha256(image.getvalue()).hexdigest()
        devices = []
        def factory():
            device = SimulatedCdc()
            device.board.drop_first_hello_ack = len(devices) == 4
            devices.append(device)
            return device
        # Public fixture token and KAT key only, never real provisioning material.
        token = 'public-cross-end-test-token-0123456789'
        relay = Relay(token, factory, queue_records=128)
        server = await relay.start('127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        try:
            with tempfile.TemporaryDirectory(prefix='eyepqc-three-end-') as folder:
                pk = Path(folder) / 'public.bin'
                pk.write_bytes(reference.G6.pk)
                for run in range(5):
                    mode = ['rekey'] if run == 2 else ['stop'] if run == 3 else []
                    process = await asyncio.create_subprocess_exec(
                        str(java), '-cp', classpath, 'org.eyepqc.mobile.NetworkCli',
                        str(pk), hashlib.sha256(reference.G6.pk).hexdigest(),
                        f'ws://127.0.0.1:{port}/stream', token, expected, *mode,
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    try:
                        stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
                    finally:
                        if process.returncode is None:
                            process.kill()
                            await process.wait()
                    self.assertEqual(process.returncode, 0, (stdout + stderr).decode(errors='replace'))
                    marker = ('ANDROID_NETWORK_' + mode[0].upper() + '_OK') if mode else 'ANDROID_NETWORK_OK'
                    self.assertIn(marker.encode(), stdout)
                    for _ in range(100):
                        if not relay.busy:
                            break
                        await asyncio.sleep(.02)
                    self.assertFalse(relay.busy)
                    self.assertTrue(devices[-1].closed)
                    expected_controls = [1, 1, 3, 5, 6] if run == 4 else [1, 3, 5, 6]
                    self.assertEqual([int(x) for x in devices[-1].commands[:len(expected_controls)]],
                                     expected_controls)
                    if mode == ['rekey']:
                        self.assertEqual([int(x) for x in devices[-1].commands[:9]],
                                         [1, 3, 5, 6, 8, 1, 3, 5, 6])
                    if mode == ['stop']:
                        self.assertEqual(int(devices[-1].commands[4]), 7)
                    print(f'THREE_END_OK session={run + 1} jpeg_sha256={expected}', flush=True)
        finally:
            server.close()
            await server.wait_closed()


if __name__ == '__main__':
    unittest.main(verbosity=2)
