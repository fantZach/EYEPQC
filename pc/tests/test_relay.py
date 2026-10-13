"""Real loopback WebSocket tests with simulated, nonblocking USB CDC."""

import asyncio
import sys
import time
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/host"))
from protocol import MessageType, encode_control, encode_usb_record
from relay import Relay, control_record, read_token
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

TOKEN = "test-only-access-token-0123456789abcdef"
HELLO = encode_usb_record(1, encode_control(MessageType.HELLO, b"\x01\x01\x00\x01" + b"h" * 32))
ACK = encode_usb_record(1, encode_control(MessageType.HELLO_ACK, b"\x01\x01\x00\x01" + b"b" * 32))
VIDEO = encode_usb_record(2, bytes(range(256)))
STOP = encode_usb_record(1, encode_control(MessageType.STOP, bytes(40)))


class FakeSerial:
    def __init__(self):
        self.input = bytearray()
        self.written = []
        self._dtr = False
        self.transitions = []
        self.closed = False
        self.on_write = None

    @property
    def dtr(self):
        return self._dtr

    @dtr.setter
    def dtr(self, value):
        self._dtr = value
        self.transitions.append((value, asyncio.get_running_loop().time()))

    def reset_input_buffer(self):
        self.input.clear()

    def reset_output_buffer(self):
        pass

    def read(self, size):
        result = bytes(self.input[:size])
        del self.input[:size]
        return result

    def write(self, data):
        self.written.append(data)
        if self.on_write:
            self.on_write(data)
        return len(data)

    def close(self):
        self.closed = True


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.devices = []

        def factory():
            device = FakeSerial()
            self.devices.append(device)
            return device

        self.relay = Relay(TOKEN, factory, partial_timeout=0.04)
        self.server = await self.relay.start("127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/stream"

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    def client(self, **kwargs):
        return connect(self.url, additional_headers={"Authorization": "Bearer " + TOKEN},
                       proxy=None, **kwargs)

    async def ready(self):
        for _ in range(200):
            if self.devices and self.devices[-1].dtr:
                return self.devices[-1]
            await asyncio.sleep(0.005)
        self.fail("USB not ready")

    async def test_authentication_and_path(self):
        for url, headers, status in [
            (self.url, {}, 401),
            (self.url, {"Authorization": "Bearer wrong"}, 401),
            (self.url, [("Authorization", "Bearer " + TOKEN)] * 2, 401),
            (self.url + "/bad", {"Authorization": "Bearer " + TOKEN}, 404),
        ]:
            with self.subTest(status=status):
                with self.assertRaises(InvalidStatus) as caught:
                    async with connect(url, additional_headers=headers, proxy=None):
                        pass
                self.assertEqual(caught.exception.response.status_code, status)
        self.assertFalse(self.devices)

    async def test_roundtrip_split_coalesced_single_viewer_and_release(self):
        async with self.client() as ws:
            device = await self.ready()
            self.assertGreaterEqual(device.transitions[1][1] - device.transitions[0][1], 0.2)
            await ws.send(HELLO)
            await asyncio.sleep(0.02)
            self.assertEqual(device.written, [HELLO])
            device.input.extend(ACK[:2])
            await asyncio.sleep(0.01)
            device.input.extend(ACK[2:] + VIDEO)
            self.assertEqual(await asyncio.wait_for(ws.recv(), 1), ACK)
            self.assertEqual(await asyncio.wait_for(ws.recv(), 1), VIDEO)
            with self.assertRaises(InvalidStatus) as caught:
                async with self.client():
                    pass
            self.assertEqual(caught.exception.response.status_code, 503)
        for _ in range(100):
            if not self.relay.busy:
                break
            await asyncio.sleep(0.005)
        self.assertTrue(device.closed)
        self.assertFalse(device.dtr)
        async with self.client() as ws:
            fresh = await self.ready()
            self.assertIsNot(fresh, device)
            await ws.send(HELLO)
            await asyncio.sleep(0.02)
            self.assertEqual(fresh.written, [HELLO])

    async def test_invalid_mobile_records(self):
        for bad in ("text", VIDEO, HELLO[:-1], b"\x01\x04\x0d" + b"x" * 1037,
                    ACK, b"\x01\x00\x01x", HELLO + HELLO,
                    HELLO[:3] + b"FAIL" + HELLO[7:]):
            with self.subTest(record=repr(bad)[:40]):
                async with self.client() as ws:
                    device = await self.ready()
                    await ws.send(bad)
                    with self.assertRaises(ConnectionClosed) as caught:
                        await asyncio.wait_for(ws.recv(), 1)
                    self.assertEqual(caught.exception.rcvd.code, 1008)
                    self.assertEqual(device.written, [])

    async def test_oversize_websocket_message(self):
        async with self.client() as ws:
            await self.ready()
            await ws.send(b"x" * 1460)
            with self.assertRaises(ConnectionClosed) as caught:
                await asyncio.wait_for(ws.recv(), 1)
            self.assertEqual(caught.exception.rcvd.code, 1009)

    async def test_invalid_usb_header_and_partial_timeout(self):
        for invalid in (b"\x02\x05\xb1", b"\x03\x00\x01x", b"\x01\x00\x00", ACK[:2]):
            async with self.client() as ws:
                device = await self.ready()
                device.input.extend(invalid)
                with self.assertRaises(ConnectionClosed) as caught:
                    await asyncio.wait_for(ws.recv(), 1)
                self.assertEqual(caught.exception.rcvd.code, 1008)

    async def test_bounded_queue_closes_instead_of_dropping(self):
        self.relay.queue_records = 1
        async with self.client() as ws:
            device = await self.ready()
            device.input.extend(ACK + ACK)
            with self.assertRaises(ConnectionClosed) as caught:
                await asyncio.wait_for(ws.recv(), 1)
            self.assertEqual(caught.exception.rcvd.code, 1008)

    async def test_partial_write_failure_releases_usb(self):
        async with self.client() as ws:
            device = await self.ready()
            device.write = lambda data: len(data) - 1
            await ws.send(HELLO)
            with self.assertRaises(ConnectionClosed) as caught:
                await asyncio.wait_for(ws.recv(), 1)
            self.assertEqual(caught.exception.rcvd.code, 1011)
        self.assertTrue(device.closed)
        self.assertFalse(device.dtr)
        self.assertFalse(self.relay.busy)

    async def test_open_failure_does_not_lock_out_next_viewer(self):
        original = self.relay.serial_factory

        def unavailable():
            raise OSError("simulated USB unavailable")

        self.relay.serial_factory = unavailable
        async with self.client() as ws:
            with self.assertRaises(ConnectionClosed) as caught:
                await asyncio.wait_for(ws.recv(), 1)
            self.assertEqual(caught.exception.rcvd.code, 1011)
        self.assertFalse(self.relay.busy)
        self.relay.serial_factory = original
        async with self.client():
            await self.ready()

    async def test_stop_close_keeps_dtr_high_until_trailing_video_quiet(self):
        ws = await self.client()
        device = await self.ready()
        stopped = asyncio.Event()
        device.on_write = lambda data: stopped.set() if data == STOP else None
        await ws.send(STOP)
        await asyncio.wait_for(stopped.wait(), 1)
        last_read = [0.0]
        original_read = device.read
        end = time.monotonic() + 0.25

        def trailing_read(size):
            if time.monotonic() < end:
                last_read[0] = time.monotonic()
                return VIDEO
            return original_read(size)

        device.read = trailing_read
        await ws.close()
        for _ in range(300):
            if device.closed:
                break
            await asyncio.sleep(0.005)
        self.assertTrue(device.closed)
        self.assertFalse(device.dtr)
        self.assertGreaterEqual(device.transitions[-1][1] - last_read[0], 0.13)
        self.assertFalse(self.relay.busy)

    async def test_stop_drain_continuous_video_has_bounded_release(self):
        ws = await self.client()
        device = await self.ready()
        stopped = asyncio.Event()
        device.on_write = lambda data: stopped.set() if data == STOP else None
        await ws.send(STOP)
        await asyncio.wait_for(stopped.wait(), 1)
        device.read = lambda size: VIDEO
        started = asyncio.get_running_loop().time()
        await ws.close()
        for _ in range(600):
            if device.closed:
                break
            await asyncio.sleep(0.005)
        elapsed = asyncio.get_running_loop().time() - started
        self.assertTrue(device.closed)
        self.assertGreaterEqual(elapsed, 1.8)
        self.assertLess(elapsed, 2.5)
        self.assertFalse(device.dtr)
        self.assertFalse(self.relay.busy)

    async def test_stop_drain_rejects_invalid_usb_and_preserves_partial_record(self):
        from protocol import UsbRecordDecoder
        device = FakeSerial()
        decoder = UsbRecordDecoder()
        decoder.feed(VIDEO[:2])
        device.input.extend(VIDEO[2:])
        self.assertEqual(await self.relay.drain_stop(device, decoder), "quiet")
        self.assertFalse(decoder.buffer)
        device.input.extend(b"\x03\x00\x01x")
        with self.assertRaises(ValueError):
            await self.relay.drain_stop(device, decoder)

    async def test_blocking_read_is_off_loop_and_completed_before_close(self):
        ws = await self.client()
        device = await self.ready()
        started = threading.Event()
        cancelled = threading.Event()
        active = [0]
        peak = [0]
        owner = threading.get_ident()
        thread_ids = []
        original_close = device.close

        def read(size):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            thread_ids.append(threading.get_ident())
            started.set()
            cancelled.wait(0.02)
            active[0] -= 1
            return b""

        def close():
            self.assertEqual(active[0], 0)
            original_close()

        device.read = read
        device.cancel_read = cancelled.set
        device.close = close
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.002)
        self.assertTrue(started.is_set())
        await ws.send(HELLO)
        for _ in range(100):
            if device.written:
                break
            await asyncio.sleep(0.002)
        self.assertEqual(device.written, [HELLO])
        await ws.close()
        for _ in range(100):
            if device.closed:
                break
            await asyncio.sleep(0.002)
        self.assertTrue(device.closed)
        self.assertFalse(cancelled.is_set())
        self.assertEqual(active[0], 0)
        self.assertEqual(peak[0], 1)
        self.assertTrue(all(identity != owner for identity in thread_ids))

    async def test_cancelled_reader_keeps_natural_partial_tail_without_cancel_io(self):
        from protocol import UsbRecordDecoder
        device = FakeSerial()
        decoder = UsbRecordDecoder()
        decoder.feed(VIDEO[:2])
        started = threading.Event()
        cancelled = threading.Event()

        def read(size):
            started.set()
            time.sleep(0.02)
            return VIDEO[2:]

        device.read = read
        device.cancel_read = cancelled.set
        task = asyncio.create_task(self.relay.usb_read(device, decoder))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.002)
        self.assertTrue(started.is_set())
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(cancelled.is_set())
        self.assertFalse(decoder.buffer)
        device.read = lambda size: b""
        self.assertEqual(await self.relay.drain_stop(device, decoder), "quiet")

    async def test_read_cancel_io_is_only_fallback_after_bounded_wait(self):
        from protocol import UsbRecordDecoder
        device = FakeSerial()
        started = threading.Event()
        cancelled = threading.Event()
        active = [0]

        def read(size):
            active[0] += 1
            started.set()
            cancelled.wait(1)
            active[0] -= 1
            return b""

        device.read = read
        device.cancel_read = cancelled.set
        task = asyncio.create_task(self.relay.usb_read(device, UsbRecordDecoder()))
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.002)
        self.assertTrue(started.is_set())
        before = time.monotonic()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertGreaterEqual(time.monotonic() - before, 0.23)
        self.assertLess(time.monotonic() - before, 0.75)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(active[0], 0)
        device.close()

    def test_inner_control_validation_and_token_file(self):
        for kind, size in ((1, 36), (3, 768), (5, 32), (6, 40), (7, 40), (8, 40)):
            body = b"\x01\x01\x00\x01" + b"h" * 32 if kind == 1 else bytes(size)
            record = encode_usb_record(1, encode_control(kind, body))
            self.assertEqual(control_record(record), record)
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text(TOKEN, encoding="ascii")
            self.assertEqual(read_token(path), TOKEN)
            path.write_text("too short", encoding="ascii")
            with self.assertRaises(ValueError):
                read_token(path)


if __name__ == "__main__":
    unittest.main()
