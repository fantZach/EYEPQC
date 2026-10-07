"""Development G6: JTAG seed/key provision, USB ML-KEM handshake, live AES-GCM JPEG."""
import argparse
from datetime import datetime
import hashlib
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from collections import Counter, deque

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image
import serial
from serial.tools import list_ports

from handshake import HostSession
from build_manifest import verify as verify_build
from m09 import Kem, OUT, PK, SK
from protocol import (MessageType, USB_CONTROL, USB_VIDEO, UsbRecordDecoder,
                      decode_control, decode_video, encode_control, encode_usb_record,
                      make_nonce)

ROOT = Path(__file__).resolve().parents[2]


def jtag(workspace, pk, sk, tool_root):
    elf = workspace / "g6_usb/build/g6_usb.elf"
    nm = tool_root / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe"
    symbols = {}
    for line in subprocess.check_output([str(nm), "-S", str(elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 4 and fields[3] in ("g6_sk_load", "g6_seed_load", "g6_ready", "g6_status"):
            symbols[fields[3]] = (int(fields[0], 16), int(fields[1], 16))
    for name, size in (("g6_sk_load", SK), ("g6_seed_load", 32),
                       ("g6_ready", 4), ("g6_status", 4)):
        address, actual = symbols[name]
        if actual != size or address % 64 or not 0x100000 <= address <= 0x40000000 - size:
            raise ValueError("invalid ELF-owned G6 buffer: " + name)
    if len(pk) != PK or len(sk) != SK or sk[768:1568] != pk:
        raise ValueError("private/public key mismatch")
    xsdb = tool_root / "Vivado/bin/xsdb.bat"
    boot = subprocess.run([str(xsdb), str(ROOT / "prj/run_usb_probe_jtag.tcl"),
                           str(workspace), "g6_usb"], capture_output=True, text=True, timeout=120)
    if boot.returncode or "USB_JTAG_RUNNING g6_usb" not in boot.stdout:
        raise RuntimeError("G6 JTAG boot failed: " + boot.stdout + boot.stderr)
    fd, name = tempfile.mkstemp(prefix="g6_seed_", dir=ROOT / "build")
    try:
        with os.fdopen(fd, "wb") as seed_file:
            seed_file.write(secrets.token_bytes(32))
        args = [str(xsdb), str(ROOT / "prj/provision_g6_jtag.tcl"),
                str(OUT / "private.bin"), name,
                *[str(symbols[item][0]) for item in
                  ("g6_sk_load", "g6_seed_load", "g6_ready", "g6_status")]]
        loaded = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if loaded.returncode or "G6_PROVISIONED" not in loaded.stdout:
            raise RuntimeError("G6 JTAG provision failed: " + loaded.stdout + loaded.stderr)
    finally:
        Path(name).unlink(missing_ok=True)


def port(timeout=10):
    deadline = time.monotonic() + timeout
    next_notice = 0.0
    while time.monotonic() < deadline:
        found = [p for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
        if len(found) == 1:
            return found[0].device
        if time.monotonic() >= next_notice:
            print("WAIT_CDC: video CDC is not enumerated yet (VID_03FD&PID_7020); "
                  "waiting for enumeration after load or reconnect",
                  flush=True)
            next_notice = time.monotonic() + 2
        time.sleep(0.2)
    raise RuntimeError("G6 USB CDC device not found")


def send_control(ser, message):
    record = encode_usb_record(USB_CONTROL, message)
    if ser.write(record) != len(record):
        raise RuntimeError("incomplete USB control write")
    ser.flush()


def read_control(ser, decoder):
    pending = pending_records(decoder)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not pending:
            pending.extend(decoder.feed(ser.read(4096)))
        if pending:
            channel, record = pending.popleft()
            if channel != USB_CONTROL:
                raise ValueError("unexpected response during handshake")
            decode_control(record)
            return record
    raise TimeoutError("G6 control response timeout")


def pending_records(decoder):
    if not hasattr(decoder, '_g6_pending'):
        decoder._g6_pending = deque()
    return decoder._g6_pending


def video_records(ser, decoder):
    pending = pending_records(decoder)
    if pending:
        records = list(pending)
        pending.clear()
        return records
    return decoder.feed(ser.read(16384))


def drain_rekey(ser, decoder, timeout=5.0, quiet=0.1):
    """Drain old video after REKEY without displaying or accepting any packets.

    The board handles REKEY after its current frame. Keep reading so its USB send
    can finish, preserving framing across partial reads. Never scan for a header.
    """
    deadline = time.monotonic() + timeout
    quiet_since = None
    pending = pending_records(decoder)
    while time.monotonic() < deadline:
        chunk = ser.read(16384)
        records = list(pending)
        pending.clear()
        records.extend(decoder.feed(chunk))
        if any(channel != USB_VIDEO for channel, _ in records):
            raise ValueError('unexpected control response while draining old video')
        if chunk or records:
            quiet_since = None
        else:
            if quiet_since is None:
                quiet_since = time.monotonic()
            if time.monotonic() - quiet_since >= quiet:
                decoder.finish()
                return
    raise TimeoutError('G6 old video did not become quiet after REKEY')


def handshake(ser, decoder, session, bad_finished=False):
    host_random = secrets.token_bytes(32)
    hello = encode_control(MessageType.HELLO, b"\x01\x01\x00\x01" + host_random)
    send_control(ser, hello)
    ack = read_control(ser, decoder)
    kind, body = decode_control(ack)
    if kind != MessageType.HELLO_ACK or body[:4] != b"\x01\x01\x00\x01":
        raise ValueError("invalid board HELLO_ACK")
    expected_hello, expected_ack, kem = session.begin(
        host_random, body[4:], secrets.token_bytes(32))
    if (hello, ack) != (expected_hello, expected_ack):
        raise ValueError("handshake transcript mismatch")
    send_control(ser, kem)
    session.verify_board_finished(read_control(ser, decoder))
    finished = session.host_finished()
    if bad_finished:
        send_control(ser, finished[:-1] + bytes([finished[-1] ^ 1]))
    else:
        send_control(ser, finished)
        send_control(ser, session.command(MessageType.START))


def frames(ser, decoder, session, seconds, output, show=False):
    window = None
    if show:
        import tkinter as tk
        from PIL import ImageTk
        window = tk.Tk()
        window.title("EYEPQC G6 authenticated video")
        label = tk.Label(window)
        label.pack()
    frame = bytearray()
    frame_id = None
    expected_frame = expected_sequence = 0
    frame_length = packet_count = timestamp = None
    resync = False
    counters = Counter()
    total = count = 0
    first = last = started = ended = None
    stream_marker_printed = False
    next_report = time.perf_counter() + 300
    aes = AESGCM(bytes(session.video_key))
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for channel, record in video_records(ser, decoder):
                if channel != USB_VIDEO:
                    raise ValueError("unexpected G6 USB channel")
                try:
                    h, aad, ciphertext, tag = decode_video(record)
                except ValueError:
                    counters['malformed_video'] += 1
                    counters['dropped_frames'] += int(bool(frame) or not resync)
                    frame.clear()
                    resync = True
                    continue
                if h.flags != 1 or h.session_id != session.session_id or h.jpeg_length > 65536:
                    counters['invalid_session_or_header'] += 1
                    counters['dropped_frames'] += int(bool(frame) or not resync)
                    frame.clear()
                    resync = True
                    continue
                try:
                    payload = aes.decrypt(make_nonce(session.epoch, h.packet_sequence),
                                          ciphertext + tag, aad)
                except InvalidTag:
                    counters['auth_failures'] += 1
                    counters['dropped_frames'] += int(bool(frame) or not resync)
                    frame.clear()
                    resync = True
                    continue
                # Authenticated headers alone may affect replay or gap accounting.
                if not session.accept_authenticated_packet(h.session_id, h.packet_sequence):
                    counters['replay_rejects'] += 1
                    counters['dropped_frames'] += int(bool(frame) or not resync)
                    frame.clear()
                    resync = True
                    continue
                if expected_sequence is not None and h.packet_sequence != expected_sequence:
                    if h.packet_sequence > expected_sequence:
                        counters['sequence_gaps'] += h.packet_sequence - expected_sequence
                    else:
                        counters['out_of_order'] += 1
                        counters['dropped_frames'] += int(bool(frame) or not resync)
                        frame.clear()
                        resync = True
                        continue
                expected_sequence = h.packet_sequence + 1
                counters['authenticated_packets'] += 1
                if resync and h.packet_id != 0:
                    counters['discarded_until_frame_start'] += 1
                    continue
                if h.packet_id == 0:
                    if frame:
                        counters['dropped_frames'] += 1
                        frame.clear()
                    if expected_frame is not None and h.frame_id != expected_frame:
                        if h.frame_id > expected_frame:
                            counters['frame_gaps'] += h.frame_id - expected_frame
                        else:
                            counters['out_of_order'] += 1
                            resync = True
                            continue
                    frame_id = h.frame_id
                    frame_length, packet_count, timestamp = h.jpeg_length, h.packet_count, h.timestamp
                    resync = False
                elif (resync or not frame or h.frame_id != frame_id or
                      h.jpeg_length != frame_length or h.packet_count != packet_count or
                      h.timestamp != timestamp):
                    counters['fragment_errors'] += 1
                    counters['dropped_frames'] += int(bool(frame) or not resync)
                    frame.clear()
                    resync = True
                    continue
                if h.packet_id != len(frame) // 1400:
                    counters['fragment_errors'] += 1
                    counters['dropped_frames'] += 1
                    frame.clear()
                    resync = True
                    continue
                frame.extend(payload)
                counters['grouped_packets'] += 1
                if h.packet_id + 1 != h.packet_count:
                    continue
                try:
                    if len(frame) != frame_length or frame[:2] != b"\xff\xd8" or frame[-2:] != b"\xff\xd9":
                        raise ValueError("invalid authenticated JPEG")
                    with Image.open(BytesIO(frame)) as image:
                        image.load()
                        if image.size != (640, 480):
                            raise ValueError("unexpected G6 camera size")
                        if window:
                            photo = ImageTk.PhotoImage(image)
                            label.configure(image=photo)
                            label.image = photo
                            window.update()
                except (ValueError, OSError):
                    counters['invalid_authenticated_jpeg'] += 1
                    counters['dropped_frames'] += 1
                    frame.clear()
                    resync = True
                    continue
                ended = time.perf_counter()
                if started is None:
                    started = ended
                    first = bytes(frame)
                last = bytes(frame)
                total += len(frame)
                count += 1
                if count >= 2 and not stream_marker_printed:
                    print(f"G6_STREAM_READY session_id={session.session_id} frames={count}",
                          flush=True)
                    stream_marker_printed = True
                expected_frame = frame_id + 1
                frame.clear()
                if ended >= next_report:
                    print(f"G6_PROGRESS frames={count} fps={(count-1)/(ended-started):.3f}",
                          flush=True)
                    next_report = ended + 300
    finally:
        if window:
            window.destroy()
    elapsed = ended - started if count > 1 else 0.0
    result = dict(frames=count, bytes=total, seconds=elapsed,
                  fps=(count - 1) / elapsed if elapsed else 0.0, output=str(output),
                  session_id=session.session_id, packets=counters['authenticated_packets'],
                  transcript_sha256=(hashlib.sha256(session.transcript).hexdigest()
                                      if session.transcript else None),
                  errors=dict(sorted(counters.items())))
    if count:
        output.mkdir(parents=True, exist_ok=True)
        (output / "first.jpg").write_bytes(first)
        (output / "last.jpg").write_bytes(last)
    return result


def require_minimum_frames(result, minimum=2):
    if result['frames'] < minimum:
        raise RuntimeError(f"insufficient authenticated G6 frames: {result['frames']} < {minimum}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT / "build/vitis/usbfix3_20261007")
    parser.add_argument("--tool-root", type=Path,
                        default=Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1")),
                        help="AMD tools install root (or set EYEPQC_TOOL_ROOT)")
    parser.add_argument("--no-jtag", action="store_true",
                        help="reuse an already provisioned, running board")
    parser.add_argument("--verify-only", action="store_true",
                        help="check build hashes without JTAG, USB or reading test private keys")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--wait-cdc", type=int, default=10,
                        help="seconds to wait for CDC after optional JTAG load/provision")
    parser.add_argument("--sessions", type=int, default=2)
    parser.add_argument("--fault-check", action="store_true",
                        help="reject a tampered Finished, then reconnect")
    parser.add_argument("--reconnect", action="store_true",
                        help="drop DTR between sessions instead of authenticated REKEY")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    if args.seconds <= 0 or not 1 <= args.sessions <= 3 or args.wait_cdc < 1:
        parser.error("seconds must be positive and sessions 1..3")
    manifest, checked = verify_build(args.workspace, 'g6_usb_manifest.json')
    if manifest.get('application') != 'g6_usb':
        raise ValueError('Expected a G6 firmware manifest')
    if args.verify_only:
        print(f'G6_PREFLIGHT_OK hashes={checked} board_accessed=false')
        return
    output = (ROOT / "data/captures" /
              ("g6_usb_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))).resolve()
    output.mkdir(parents=True)
    record = {
        "status": "running", "parameters": {
            "seconds": args.seconds, "sessions": args.sessions,
            "fault_check_bad_finished": args.fault_check,
            "reconnect_dtr": args.reconnect, "show": args.show,
            "jtag_load": not args.no_jtag,
        },
        "build": {
            "manifest_sha256": hashlib.sha256(
                (args.workspace / "g6_usb_manifest.json").read_bytes()).hexdigest(),
            "elf_sha256": hashlib.sha256(
                (args.workspace / "g6_usb/build/g6_usb.elf").read_bytes()).hexdigest(),
            "xsa_sha256": manifest.get("xsa_sha256"),
        },
        "board_counters": None,
        "sessions": [],
    }
    record_path = output / "result.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    pk = pin = sk = None
    device = None
    ser = None
    session = None
    previous_key = None
    result = record["sessions"]
    try:
        pk = (OUT / "public.bin").read_bytes()
        sk = bytearray((OUT / "private.bin").read_bytes())
        pin = bytes.fromhex((OUT / "public.sha256").read_text().strip())
        if hashlib.sha256(pk).digest() != pin or sk[768:1568] != pk:
            raise ValueError("pinned G6 test key mismatch")
        if not args.no_jtag:
            record["jtag_started"] = True
            record_path.write_text(json.dumps(record, indent=2) + "\n")
            jtag(args.workspace.resolve(), pk, sk, args.tool_root.resolve())
            record["jtag_completed"] = True
        session = HostSession(pk, pin, Kem())
        device = port(args.wait_cdc)
        ser = serial.Serial(port=None, baudrate=115200, timeout=0.25)
        ser.dtr = False
        ser.port = device
        for attempt in range(20):
            try:
                ser.open()
                break
            except serial.SerialException:
                if attempt == 19:
                    raise
                time.sleep(0.5)  # Windows may publish COM before CDC is ready to configure.
        ser.reset_input_buffer()
        ser.dtr = True
        decoder = UsbRecordDecoder()
        if args.fault_check:
            handshake(ser, decoder, session, bad_finished=True)
            if ser.read(1):
                raise RuntimeError("video sent after invalid host Finished")
            ser.dtr = False
            time.sleep(0.2)
            ser.reset_input_buffer()
            ser.dtr = True
            session.close("ERROR")
            decoder = UsbRecordDecoder()
        for index in range(args.sessions):
            handshake(ser, decoder, session)
            current_key = bytearray(session.video_key)
            key_changed = None if previous_key is None else not hmac.compare_digest(
                previous_key, current_key)
            if key_changed is False:
                raise RuntimeError("fresh G6 handshake repeated the prior video key")
            result.append(frames(ser, decoder, session, args.seconds,
                                 output / f"session_{index+1}", args.show))
            require_minimum_frames(result[-1])
            result[-1]['key_changed'] = key_changed
            if previous_key is not None:
                previous_key[:] = bytes(len(previous_key))
            previous_key = current_key
            if index + 1 < args.sessions and args.reconnect:
                ser.dtr = False
                time.sleep(0.2)
                ser.reset_input_buffer()
                ser.dtr = True
                session.close("ERROR")
                decoder = UsbRecordDecoder()
            else:
                kind = MessageType.REKEY if index + 1 < args.sessions else MessageType.STOP
                send_control(ser, session.command(kind))
            if index + 1 < args.sessions and not args.reconnect:
                drain_rekey(ser, decoder)
                decoder = UsbRecordDecoder()
        record["status"] = "passed"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = {"class": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        if ser is not None:
            try:
                ser.dtr = False
                ser.close()
            except (serial.SerialException, OSError):
                pass
        if previous_key is not None:
            previous_key[:] = bytes(len(previous_key))
        if sk is not None:
            sk[:] = bytes(len(sk))
        if session is not None:
            session.close()
        record_path.write_text(json.dumps(record, indent=2) + "\n")
    print(f"G6_USB_OK port={device} sessions={len(result)} "
          f"fps={[round(x['fps'], 3) for x in result]} "
          f"fault_check={args.fault_check} reconnect={args.reconnect} output={output}")


if __name__ == "__main__":
    main()
