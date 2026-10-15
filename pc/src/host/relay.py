"""Windows USB CDC ↔ WebSocket ciphertext relay; no business keys or decoding."""

import argparse
from accounts import Accounts
import asyncio
import hmac
import hashlib
import json
import logging
from http import HTTPStatus
from pathlib import Path
import ssl
import time
from urllib.parse import urlsplit

import serial
from serial.tools import list_ports
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from protocol import (MessageType, USB_CONTROL, USB_LIMITS, USB_VIDEO, UsbRecordDecoder,
                      decode_control, decode_video, encode_usb_record)


def read_token(path):
    token = Path(path).read_text(encoding="ascii").strip()
    if not 32 <= len(token) <= 256 or not all(33 <= ord(c) <= 126 for c in token):
        raise ValueError("token file must contain 32..256 printable non-space ASCII characters")
    return token


def read_pairing(path):
    """Load only a bounded public schema2 document, never a directory or credentials."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate pairing field")
            result[key] = value
        return result
    with Path(path).open("rb") as source:
        data = source.read(8193)
    if not 0 < len(data) <= 8192:
        raise ValueError("pairing size")
    config = json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    if (not isinstance(config, dict) or set(config) !=
            {"version", "endpoint", "public_key_hex", "public_key_sha256"} or
            type(config["version"]) is not int or config["version"] != 2 or
            any(not isinstance(config[field], str) for field in config if field != "version")):
        raise ValueError("public schema2 pairing required")
    endpoint = config["endpoint"]
    address = urlsplit(endpoint)
    if (address.scheme != "wss" or not address.hostname or address.username is not None or
            address.password is not None or address.path != "/stream" or "?" in endpoint or
            "#" in endpoint or address.port == 0 or
            any(ord(c) <= 32 or ord(c) > 126 for c in endpoint)):
        raise ValueError("pairing requires a WSS stream endpoint")
    key_hex, pin_hex = config["public_key_hex"], config["public_key_sha256"]
    if (len(key_hex) != 1600 or len(pin_hex) != 64 or
            any(c not in "0123456789abcdefABCDEF" for c in key_hex + pin_hex) or
            not hmac.compare_digest(hashlib.sha256(bytes.fromhex(key_hex)).digest(), bytes.fromhex(pin_hex))):
        raise ValueError("pairing public identity mismatch")
    return data


def control_record(message):
    if not isinstance(message, bytes) or len(message) < 4:
        raise ValueError("one binary USB control record required")
    size = int.from_bytes(message[1:3], "big")
    if message[0] != USB_CONTROL or not 1 <= size <= USB_LIMITS[USB_CONTROL] or len(message) != size + 3:
        raise ValueError("invalid control channel or length")
    kind, _ = decode_control(message[3:])
    if kind not in (MessageType.HELLO, MessageType.KEM_CIPHERTEXT, MessageType.FINISHED_HOST,
                    MessageType.START, MessageType.STOP, MessageType.REKEY, MessageType.EPHEMERAL_CIPHERTEXT):
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
    def __init__(self, token=None, serial_factory=open_cdc, *, accounts=None, queue_records=64,
                 partial_timeout=2.0, send_timeout=5.0, pairing_file=None):
        if queue_records < 1 or partial_timeout <= 0 or send_timeout <= 0:
            raise ValueError("queue and timeouts must be positive")
        if (token is None) == (accounts is None):
            raise ValueError("select exactly one authentication mode")
        if pairing_file is not None and accounts is None:
            raise ValueError("automatic pairing requires TLS account mode")
        self.pairing = read_pairing(pairing_file) if pairing_file is not None else None
        self.accounts = accounts
        self.owner = None
        self.owner_user = None
        self.handoff = asyncio.Lock()
        self.verifying = False
        self.cleanup_failed = False
        self.token = token
        self.serial_factory = serial_factory
        self.queue_records = queue_records
        self.partial_timeout = partial_timeout
        self.send_timeout = send_timeout
        self.busy = False

    async def authorize(self, connection, request):
        allowed = ("/stream", "/stream?takeover=1") if self.accounts else ("/stream",)
        if self.pairing is not None:
            allowed += ("/pairing.json",)
        if request.path not in allowed:
            return connection.respond(HTTPStatus.NOT_FOUND, "Unknown endpoint\n")
        values = request.headers.get_all("Authorization")
        if self.accounts:
            if not self.accounts.admit():
                return connection.respond(HTTPStatus.TOO_MANY_REQUESTS, "Rate limited\n")
            if self.verifying:
                return connection.respond(HTTPStatus.TOO_MANY_REQUESTS, "Authentication busy\n")
            self.verifying = True
            pending = asyncio.create_task(asyncio.to_thread(self.accounts.verify, values[0] if len(values) == 1 else ""))
            try:
                try:
                    user = await asyncio.shield(pending)
                except asyncio.CancelledError:
                    await asyncio.shield(pending)
                    raise
            finally:
                self.verifying = False
            if user is None:
                return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
            if request.path == "/pairing.json":
                response = connection.respond(HTTPStatus.OK, self.pairing.decode("utf-8"))
                response.headers["Content-Type"] = "application/json; charset=utf-8"
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response
            connection.relay_user = user
            connection.relay_takeover = request.path.endswith("?takeover=1")
            if self.cleanup_failed:
                return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "USB cleanup failed\n")
            if self.busy and user == self.owner_user and not connection.relay_takeover:
                return connection.respond(HTTPStatus.CONFLICT, "Confirm takeover\n")
        else:
            if len(values) != 1 or not hmac.compare_digest(values[0].encode(), ("Bearer " + self.token).encode()):
                return connection.respond(HTTPStatus.UNAUTHORIZED, "Unauthorized\n")
        if self.cleanup_failed or (self.busy and (not self.accounts or connection.relay_user != self.owner_user)):
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "Viewer unavailable\n")

    async def usb_reader(self, device, queue, decoder, stats):
        partial_since = None
        video_frame = None
        dropping_frame = False
        while True:
            data = await self.usb_read(device, decoder)
            if data:
                records = decoder.feed(data)
                stats["usb_records"] += len(records)
                pending_controls = sum(channel == USB_CONTROL for channel, _ in records)
                if queue.qsize() + pending_controls > queue.maxsize:
                    raise asyncio.QueueFull
                for channel, payload in records:
                    if channel == USB_CONTROL:
                        pending_controls -= 1
                        kind, _ = decode_control(payload)
                        if kind not in (MessageType.HELLO_ACK, MessageType.FINISHED_BOARD,
                                        MessageType.ERROR, MessageType.EPHEMERAL_PUBLIC):
                            raise ValueError("control type is not board-to-mobile")
                    elif channel == USB_VIDEO:
                        header, _, _, _ = decode_video(payload)
                        frame = (header.session_id, header.frame_id)
                        if frame != video_frame:
                            video_frame = frame
                            # Reserve capacity for a complete frame, never stall USB behind the WAN.
                            # shortcut: Frames larger than this fixed queue are dropped; use byte budgeting for larger resolutions.
                            dropping_frame = (header.packet_id != 0 or
                                header.packet_count > queue.maxsize - queue.qsize() - pending_controls)
                            if dropping_frame:
                                stats["video_frames_dropped"] += 1
                        if dropping_frame:
                            stats["video_records_dropped"] += 1
                            continue
                    queue.put_nowait(encode_usb_record(channel, payload))
                stats["queue_peak"] = max(stats["queue_peak"], queue.qsize())
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

    async def network_sender(self, websocket, queue, stats):
        unacknowledged = 0
        while True:
            record = await queue.get()
            await asyncio.wait_for(websocket.send(record), self.send_timeout)
            stats["network_records"] += 1
            stats["network_bytes"] += len(record)
            unacknowledged += len(record)
            if unacknowledged >= 65536:
                # Bound bytes beyond this queue, including SSH/TCP buffering, using standard WS control frames.
                async with asyncio.timeout(self.send_timeout):
                    pong = await websocket.ping()
                    await pong
                unacknowledged = 0

    async def network_reader(self, websocket, device, stats):
        async for message in websocket:
            if self.owner is not websocket:
                return
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
        async with self.handoff:
            if self.cleanup_failed:
                await websocket.close(1011, "USB cleanup failed")
                return
            if self.busy:
                if (not self.accounts or websocket.relay_user != self.owner_user
                        or not websocket.relay_takeover or self.owner is None):
                    await websocket.close(1013, "Viewer already connected")
                    return
                old = self.owner
                self.owner = None  # Fence writes before any await during takeover.
                try:
                    await old.close(4409, "Taken over")
                    await asyncio.wait_for(old.relay_done.wait(), 3)
                except (TimeoutError, OSError, ConnectionClosed):
                    self.cleanup_failed = True
                if self.cleanup_failed:
                    await websocket.close(1011, "USB cleanup failed")
                    return
            self.busy = True
            self.owner = websocket
            self.owner_user = getattr(websocket, 'relay_user', None)
            websocket.relay_done = asyncio.Event()
        device = None
        tasks = []
        close_code = 1000
        reason = "Session closed"
        error = "none"
        started = time.monotonic()
        decoder = UsbRecordDecoder()
        stats = dict(stop_forwarded=False, mobile_controls=0, usb_records=0,
                     network_records=0, network_bytes=0, queue_peak=0,
                     video_frames_dropped=0, video_records_dropped=0)
        try:
            device = self.serial_factory()
            device.dtr = False
            device.reset_input_buffer()
            device.reset_output_buffer()
            await asyncio.sleep(0.25)
            device.reset_input_buffer()
            device.dtr = True
            print(f"RELAY_SESSION_OPEN peer={websocket.remote_address} "
                  f"serial={getattr(device, 'port', 'simulated')}", flush=True)
            queue = asyncio.Queue(maxsize=self.queue_records)
            tasks = [asyncio.create_task(self.usb_reader(device, queue, decoder, stats)),
                     asyncio.create_task(self.network_sender(websocket, queue, stats)),
                     asyncio.create_task(self.network_reader(websocket, device, stats))]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (ValueError, asyncio.QueueFull) as exc:
            error = type(exc).__name__
            close_code, reason = 1008, "Invalid record or bounded queue exceeded"
        except (TimeoutError, OSError, RuntimeError, serial.SerialException) as exc:
            error = type(exc).__name__
            close_code, reason = 1011, "USB or transport failure"
        except ConnectionClosed:
            if websocket.close_code not in (None, 1000, 1001):
                close_code, reason = 1011, "Abnormal WebSocket closure"
                error = f"WebSocket{websocket.close_code}"
        finally:
            cancelled_during_drain = False
            for task in tasks:
                task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            if close_code == 1000 and any(isinstance(result, ValueError) for result in results):
                close_code, reason = 1008, "Invalid USB record during cleanup"
                error = "ValueError"
            elif close_code == 1000 and any(isinstance(result, (OSError, serial.SerialException)) for result in results):
                close_code, reason = 1011, "USB failure during cleanup"
                error = "USBError"
            if device is not None:
                if stats["stop_forwarded"] and close_code == 1000:
                    try:
                        if await self.drain_stop(device, decoder) != "quiet":
                            self.cleanup_failed = True
                    except ValueError:
                        close_code, reason = 1008, "Invalid USB record during STOP drain"
                        error = "ValueError"
                        print("RELAY_STOP_DRAIN outcome=invalid", flush=True)
                    except (OSError, serial.SerialException):
                        close_code, reason = 1011, "USB failure during STOP drain"
                        error = "USBError"
                        print("RELAY_STOP_DRAIN outcome=usb_failure", flush=True)
                    except asyncio.CancelledError:
                        cancelled_during_drain = True
                try:
                    device.dtr = False
                    device.reset_input_buffer()
                    device.reset_output_buffer()
                except (OSError, serial.SerialException):
                    self.cleanup_failed = True
                finally:
                    try:
                        device.close()
                    except (OSError, serial.SerialException):
                        self.cleanup_failed = True
            if self.owner is websocket:
                self.owner = None
            if self.owner is None or self.owner is websocket:
                self.busy = self.cleanup_failed
            websocket.relay_done.set()
            print(f"RELAY_SESSION_CLOSE code={close_code} stop_forwarded={int(stats['stop_forwarded'])} "
                  f"mobile_controls={stats['mobile_controls']} usb_records={stats['usb_records']} "
                  f"network_records={stats['network_records']} network_bytes={stats['network_bytes']} "
                  f"video_frames_dropped={stats['video_frames_dropped']} video_records_dropped={stats['video_records_dropped']} "
                  f"queue_peak={stats['queue_peak']} duration_s={time.monotonic() - started:.3f} "
                  f"error={error} reason={reason!r}", flush=True)
            if cancelled_during_drain:
                raise asyncio.CancelledError
            await websocket.close(close_code, reason)

    async def start(self, host="127.0.0.1", port=8765, *, tls=None):
        if self.accounts and tls is None:
            raise ValueError("account mode requires TLS")
        logger = logging.getLogger("eyepqc.relay.websocket")
        # Protocol DEBUG dumps Authorization headers, even if parent logging enables it.
        logger.setLevel(logging.INFO)
        return await serve(self.handle, host, port, process_request=self.authorize,
                           compression=None, max_size=1459, max_queue=16,
                           write_limit=32768, close_timeout=2, ssl=tls,
                           logger=logger)


async def run(args, *, ready=None):
    tls = None
    if bool(args.tls_cert) != bool(args.tls_key):
        raise ValueError("--tls-cert and --tls-key must be supplied together")
    if args.tls_cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.tls_cert, args.tls_key)
    relay = Relay(read_token(args.token_file) if args.token_file else None,
                  lambda: open_cdc(args.serial_port),
                  accounts=Accounts(args.accounts_file) if args.accounts_file else None,
                  pairing_file=args.pairing_file)
    async with await relay.start(args.host, args.port, tls=tls) as server:
        print(f"RELAY_READY {'wss' if tls else 'ws'}://{args.host}:{args.port}/stream", flush=True)
        if ready is not None:
            ready.set()
        await server.serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    auth = parser.add_mutually_exclusive_group(required=True)
    auth.add_argument("--token-file", type=Path)
    auth.add_argument("--accounts-file", type=Path)
    parser.add_argument("--pairing-file", type=Path, help="Public schema2 JSON served only after TLS account login")
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
