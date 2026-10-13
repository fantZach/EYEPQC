"""Windows USB CDC ↔ WebSocket ciphertext relay; no business keys or decoding."""

import argparse
import asyncio
import hmac
import logging
from http import HTTPStatus
from pathlib import Path
import ssl
import time

import serial
from serial.tools import list_ports
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from protocol import (MessageType, USB_CONTROL, USB_LIMITS, UsbRecordDecoder,
                      decode_control, encode_usb_record)


def read_token(path):
    token = Path(path).read_text(encoding="ascii").strip()
    if not 32 <= len(token) <= 256 or not all(33 <= ord(c) <= 126 for c in token):
        raise ValueError("token file must contain 32..256 printable non-space ASCII characters")
    return token


def control_record(message):
    if not isinstance(message, bytes) or len(message) < 4:
        raise ValueError("one binary USB control record required")
    size = int.from_bytes(message[1:3], "big")
    if message[0] != USB_CONTROL or not 1 <= size <= USB_LIMITS[USB_CONTROL] or len(message) != size + 3:
        raise ValueError("invalid control channel or length")
    kind, _ = decode_control(message[3:])
    if kind not in (MessageType.HELLO, MessageType.KEM_CIPHERTEXT, MessageType.FINISHED_HOST,
                    MessageType.START, MessageType.STOP, MessageType.REKEY):
        raise ValueError("control type is not mobile-to-board")
    return message


def open_cdc(port=None):
    if port is None:
        ports = [p.device for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
        if len(ports) != 1:
            raise RuntimeError("exactly one VID_03FD&PID_7020 video CDC required; use --serial-port")
        port = ports[0]
    # Apply DTR only after stale input is cleared. Windows serial handles are exclusive.
    device = serial.Serial(port=None, baudrate=115200, timeout=0.02, write_timeout=0.25)
    device.dtr = False
    device.port = port
    device.open()
    return device


class Relay:
    def __init__(self, token, serial_factory=open_cdc, *, queue_records=64,
                 partial_timeout=2.0, send_timeout=5.0):
        if queue_records < 1 or partial_timeout <= 0 or send_timeout <= 0:
            raise ValueError("queue and timeouts must be positive")
        self.token = token
        self.serial_factory = serial_factory
        self.queue_records = queue_records
        self.partial_timeout = partial_timeout
        self.send_timeout = send_timeout
        self.busy = False

    def authorize(self, connection, request):
        if request.path != "/stream":
            return connection.respond(HTTPStatus.NOT_FOUND, "Unknown endpoint\n")
        values = request.headers.get_all("Authorization")
        if len(values) != 1 or not hmac.compare_digest(values[0].encode(), ("Bearer " + self.token).encode()):
            return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        if self.busy:
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "Viewer already connected\n")

    async def usb_reader(self, device, queue, decoder, stats):
        partial_since = None
        while True:
            data = await self.usb_read(device, decoder)
            if data:
                records = decoder.feed(data)
                stats["usb_records"] += len(records)
                if queue.qsize() + len(records) > queue.maxsize:
                    raise asyncio.QueueFull
                for channel, payload in records:
                    queue.put_nowait(encode_usb_record(channel, payload))
                if not decoder.buffer:
                    partial_since = None
                elif partial_since is None or records:
                    partial_since = time.monotonic()
            if partial_since is not None and time.monotonic() - partial_since > self.partial_timeout:
                raise ValueError("USB partial record timeout")

    async def usb_read(self, device, decoder):
        # Positive timeout issues Windows ReadFile even when cbInQue is empty.
        pending = asyncio.create_task(asyncio.to_thread(device.read, 4096))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            # The port must not be reset/closed or drained until this read exits.
            # Natural timeout preserves bytes Windows may already have consumed.
            try:
                trailing = await asyncio.wait_for(asyncio.shield(pending), 0.25)
            except TimeoutError:
                cancel_read = getattr(device, "cancel_read", None)
                if cancel_read is not None:
                    try:
                        cancel_read()
                    except (OSError, serial.SerialException):
                        pass
                trailing = await asyncio.shield(pending)
            if trailing:
                decoder.feed(trailing)
            raise

    async def network_sender(self, websocket, queue):
        while True:
            record = await queue.get()
            await asyncio.wait_for(websocket.send(record), self.send_timeout)

    async def network_reader(self, websocket, device, stats):
        async for message in websocket:
            record = control_record(message)
            # Control-only writes are bounded by the port's 250 ms write timeout.
            if device.write(record) != len(record):
                raise IOError("incomplete USB control write")
            kind, _ = decode_control(record[3:])
            stats["stop_forwarded"] = kind == MessageType.STOP
            stats["mobile_controls"] += 1

    async def drain_stop(self, device, decoder):
        """Discard validated trailing records after STOP, keeping DTR high until quiet."""
        started = quiet_since = time.monotonic()
        records = total = 0
        outcome = "timeout"
        while time.monotonic() - started < 2.0:
            data = await self.usb_read(device, decoder)
            if data:
                records += len(decoder.feed(data))
                total += len(data)
                quiet_since = time.monotonic()
            elif not decoder.buffer and time.monotonic() - quiet_since >= 0.15:
                outcome = "quiet"
                break
        print(f"RELAY_STOP_DRAIN outcome={outcome} records={records} bytes={total}", flush=True)
        return outcome

    async def handle(self, websocket):
        # The upgrade and handler may race; this guard also rejects a simultaneous upgrade.
        if self.busy:
            await websocket.close(1013, "Viewer already connected")
            return
        self.busy = True
        device = None
        tasks = []
        close_code = 1000
        reason = "Session closed"
        decoder = UsbRecordDecoder()
        stats = dict(stop_forwarded=False, mobile_controls=0, usb_records=0)
        try:
            device = self.serial_factory()
            device.dtr = False
            device.reset_input_buffer()
            device.reset_output_buffer()
            await asyncio.sleep(0.25)
            device.reset_input_buffer()
            device.dtr = True
            print("RELAY_SESSION_OPEN", flush=True)
            queue = asyncio.Queue(maxsize=self.queue_records)
            tasks = [asyncio.create_task(self.usb_reader(device, queue, decoder, stats)),
                     asyncio.create_task(self.network_sender(websocket, queue)),
                     asyncio.create_task(self.network_reader(websocket, device, stats))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ValueError, asyncio.QueueFull):
            close_code, reason = 1008, "Invalid record or bounded queue exceeded"
        except (TimeoutError, OSError, RuntimeError, serial.SerialException):
            close_code, reason = 1011, "USB or transport failure"
        except ConnectionClosed:
            if websocket.close_code not in (None, 1000, 1001):
                close_code, reason = 1011, "Abnormal WebSocket closure"
        finally:
            cancelled_during_drain = False
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if any(isinstance(result, ValueError) for result in results):
                close_code, reason = 1008, "Invalid USB record during cleanup"
            elif any(isinstance(result, (OSError, serial.SerialException)) for result in results):
                close_code, reason = 1011, "USB failure during cleanup"
            if device is not None:
                if stats["stop_forwarded"] and close_code == 1000:
                    try:
                        await self.drain_stop(device, decoder)
                    except ValueError:
                        close_code, reason = 1008, "Invalid USB record during STOP drain"
                        print("RELAY_STOP_DRAIN outcome=invalid", flush=True)
                    except (OSError, serial.SerialException):
                        close_code, reason = 1011, "USB failure during STOP drain"
                        print("RELAY_STOP_DRAIN outcome=usb_failure", flush=True)
                    except asyncio.CancelledError:
                        cancelled_during_drain = True
                try:
                    device.dtr = False
                    device.reset_input_buffer()
                    device.reset_output_buffer()
                except (OSError, serial.SerialException):
                    pass
                finally:
                    try:
                        device.close()
                    except (OSError, serial.SerialException):
                        pass
            self.busy = False
            print(f"RELAY_SESSION_CLOSE code={close_code} stop_forwarded={int(stats['stop_forwarded'])} "
                  f"mobile_controls={stats['mobile_controls']} usb_records={stats['usb_records']}", flush=True)
            if cancelled_during_drain:
                raise asyncio.CancelledError
            await websocket.close(close_code, reason)

    async def start(self, host="127.0.0.1", port=8765, *, tls=None):
        return await serve(self.handle, host, port, process_request=self.authorize,
                           compression=None, max_size=1459, max_queue=16,
                           write_limit=32768, close_timeout=2, ssl=tls,
                           logger=logging.getLogger("eyepqc.relay.websocket"))


async def run(args):
    tls = None
    if bool(args.tls_cert) != bool(args.tls_key):
        raise ValueError("--tls-cert and --tls-key must be supplied together")
    if args.tls_cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.tls_cert, args.tls_key)
    relay = Relay(read_token(args.token_file), lambda: open_cdc(args.serial_port))
    async with await relay.start(args.host, args.port, tls=tls) as server:
        print(f"RELAY_READY {'wss' if tls else 'ws'}://{args.host}:{args.port}/stream", flush=True)
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1", help="PC LAN or VPN interface address")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--serial-port", help="optional COM port override")
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
