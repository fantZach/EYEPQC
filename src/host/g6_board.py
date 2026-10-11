"""Development G6: JTAG seed/key provision, USB ML-KEM handshake, live AES-GCM JPEG."""
import argparse
from datetime import datetime
import faulthandler
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


def atomic_write(path, payload):
    """Atomically replace a capture artifact, retrying brief Windows reader locks."""
    path = Path(path)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(payload)

        deadline = time.monotonic() + 1.5
        delay = 0.01
        while True:
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                retryable_winerrors = (5, 32, 33)  # ACCESS_DENIED, SHARING_VIOLATION, LOCK_VIOLATION
                remaining = deadline - time.monotonic()
                if (os.name != "nt" or getattr(exc, "winerror", None) not in retryable_winerrors
                        or remaining <= 0):
                    raise
                time.sleep(min(delay, remaining))
                delay = min(delay * 2, 0.1)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_result(path, record):
    atomic_write(path, json.dumps(record, indent=2) + "\n")


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


def port(timeout=10, cancelled=None):
    deadline = time.monotonic() + timeout
    next_notice = 0.0
    while time.monotonic() < deadline:
        if cancelled and cancelled():
            raise InterruptedError('connection cancelled')
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


def send_control(ser, message, stage="control"):
    record = encode_usb_record(USB_CONTROL, message)
    bounded = getattr(ser, "write_timeout", None) is not None
    if bounded:
        print(f"G6_HOST_STAGE stage={stage}_write_begin", flush=True)
    if ser.write(record) != len(record):
        raise RuntimeError("incomplete USB control write")
    if bounded:
        deadline = time.monotonic() + 1.0
        while ser.out_waiting:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"G6 USB control write drain timeout at {stage}")
            time.sleep(0.01)
        print(f"G6_HOST_STAGE stage={stage}_write_complete", flush=True)
    else:
        ser.flush()


def read_control(ser, decoder, cancelled=None, debug_stage=False, timeout=10.0,
                 ignore_records=()):
    pending = pending_records(decoder)
    deadline = time.monotonic() + timeout
    read_calls = raw_bytes = 0
    decoded_channels = Counter()
    while time.monotonic() < deadline:
        if cancelled and cancelled():
            raise InterruptedError('handshake cancelled')
        if not pending:
            chunk = ser.read(4096)
            read_calls += 1
            raw_bytes += len(chunk)
            records = decoder.feed(chunk)
            for channel, _ in records:
                decoded_channels[channel] += 1
            pending.extend(records)
        if pending:
            channel, record = pending.popleft()
            if channel == USB_CONTROL and record in ignore_records:
                if debug_stage:
                    print("G6_HOST_DIAG stage=duplicate_control_ignored "
                          f"channel={channel} record_bytes={len(record)}", flush=True)
                continue
            if channel != USB_CONTROL:
                if debug_stage:
                    print(f"G6_HOST_DIAG stage=unexpected_control_channel channel={channel} "
                          f"rx_bytes={raw_bytes} decoder_buffer_bytes={len(decoder.buffer)}",
                          flush=True)
                raise ValueError("unexpected response during handshake")
            decode_control(record)
            return record
    if debug_stage:
        buffer = decoder.buffer
        channel = buffer[0] if buffer else -1
        declared_length = int.from_bytes(buffer[1:3], 'big') if len(buffer) >= 3 else -1
        print("G6_HOST_DIAG stage=control_response_timeout "
              f"reads={read_calls} rx_bytes={raw_bytes} "
              f"decoded_control={decoded_channels[USB_CONTROL]} "
              f"decoded_video={decoded_channels[USB_VIDEO]} "
              f"decoder_buffer_bytes={len(buffer)} decoder_channel={channel} "
              f"decoder_declared_length={declared_length}", flush=True)
    raise TimeoutError("G6 control response timeout")


def read_hello_ack(ser, decoder, hello, cancelled=None, debug_stage=False,
                   attempt_timeout=3.0, max_retries=2):
    """Retry the same HELLO when its unauthenticated ACK is lost in transport.

    The board must replay its cached HELLO_ACK for an identical HELLO while in
    WAIT_KEM. Reusing the exact request keeps the handshake transcript stable.
    """
    if attempt_timeout <= 0 or max_retries < 0:
        raise ValueError("HELLO_ACK retry bounds must be positive")
    for attempt in range(max_retries + 1):
        try:
            return read_control(ser, decoder, cancelled, debug_stage,
                                timeout=attempt_timeout)
        except TimeoutError:
            if decoder.buffer:
                if debug_stage:
                    print("G6_HOST_DIAG stage=hello_ack_retry_suppressed "
                          f"reason=partial_record buffer_bytes={len(decoder.buffer)}",
                          flush=True)
                raise
            if attempt >= max_retries:
                raise
            if debug_stage:
                print(f"G6_HOST_STAGE stage=hello_ack_retry attempt={attempt + 1}/{max_retries}",
                      flush=True)
            send_control(ser, hello, stage=f"hello_retry_{attempt + 1}")
    raise AssertionError("unreachable HELLO_ACK retry state")


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
    """Drain final video until quiet without accepting any control packets.

    The board handles session commands after its current frame. Keep reading so its
    USB send can finish, preserving framing across partial reads. Never scan for a
    header. Used for REKEY by default and for STOP only by an explicit candidate flag.
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


def stop_and_drain(ser, decoder, session, enabled=False, timeout=5.0, quiet=0.1):
    """Send authenticated STOP and optionally drain video before closing CDC."""
    send_control(ser, session.command(MessageType.STOP))
    if enabled:
        drain_rekey(ser, decoder, timeout=timeout, quiet=quiet)


def handshake(ser, decoder, session, bad_finished=False, cancelled=None, debug_stage=False,
              hello_ack_timeout=3.0, hello_ack_retries=2):
    host_random = secrets.token_bytes(32)
    hello = encode_control(MessageType.HELLO, b"\x01\x01\x00\x01" + host_random)
    send_control(ser, hello, stage="hello")
    if debug_stage:
        print("G6_HOST_STAGE stage=hello_ack_wait_begin", flush=True)
    ack = read_hello_ack(ser, decoder, hello, cancelled, debug_stage=debug_stage,
                         attempt_timeout=hello_ack_timeout,
                         max_retries=hello_ack_retries)
    if debug_stage:
        print("G6_HOST_STAGE stage=hello_ack_received", flush=True)
    kind, body = decode_control(ack)
    if kind != MessageType.HELLO_ACK or body[:4] != b"\x01\x01\x00\x01":
        raise ValueError("invalid board HELLO_ACK")
    expected_hello, expected_ack, kem = session.begin(
        host_random, body[4:], secrets.token_bytes(32))
    if (hello, ack) != (expected_hello, expected_ack):
        raise ValueError("handshake transcript mismatch")
    send_control(ser, kem, stage="kem")
    if debug_stage:
        print("G6_HOST_STAGE stage=board_finished_wait_begin", flush=True)
    session.verify_board_finished(read_control(ser, decoder, cancelled,
                                               debug_stage=debug_stage,
                                               ignore_records=(ack,)))
    if debug_stage:
        print("G6_HOST_STAGE stage=board_finished_received", flush=True)
    finished = session.host_finished()
    if bad_finished:
        send_control(ser, finished[:-1] + bytes([finished[-1] ^ 1]))
    else:
        send_control(ser, finished)
        send_control(ser, session.command(MessageType.START))


def frames(ser, decoder, session, seconds, output, show=False, *,
           on_frame=None, on_stats=None, should_stop=None, transform=None,
           on_verified_frame=None):
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
    def snapshot():
        elapsed = ended - started if count > 1 else 0.0
        return dict(frames=count, bytes=total, fps=(count - 1) / elapsed if elapsed else 0.0,
                    session_id=session.session_id, errors=dict(counters))
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if should_stop and should_stop():
                break
            if on_stats:
                on_stats(snapshot())
            for channel, record in video_records(ser, decoder):
                if channel != USB_VIDEO:
                    raise ValueError("unexpected G6 USB channel")
                if transform:
                    record = transform(record)
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
                if on_frame:
                    on_frame(last, h, snapshot())
                if on_verified_frame:
                    output.mkdir(parents=True, exist_ok=True)
                    def save_snapshot(name, payload):
                        atomic_write(output / name, payload)
                    if count == 1:
                        save_snapshot("first.jpg", first)
                    save_snapshot("last.jpg", last)
                    on_verified_frame(count, total, counters.copy())
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
        atomic_write(output / "first.jpg", first)
        atomic_write(output / "last.jpg", last)
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
    parser.add_argument("--report-key-fingerprint", action="store_true",
                        help="record SHA-256 of each derived video key for cross-process uniqueness checks")
    parser.add_argument("--drain-stop", action="store_true",
                        help="after STOP, drain authenticated video to a quiet boundary before DTR close")
    parser.add_argument("--bounded-control-write", action="store_true",
                        help="bound control writes and report handshake progress without payloads")
    parser.add_argument("--debug-stage", action="store_true",
                        help="record key-free host stage markers and a delayed Python stack dump")
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
    write_result(record_path, record)
    print(f"G6_RUN_RESULT path={record_path}", flush=True)
    stack_dump = None
    if args.debug_stage:
        stack_dump = (output / "host_stack_timeout.log").open("w", encoding="utf-8")
        faulthandler.dump_traceback_later(30, file=stack_dump, repeat=False)
    def stage(name):
        if args.debug_stage:
            print(f"G6_HOST_STAGE stage={name}", flush=True)
    pk = pin = sk = None
    device = None
    ser = None
    session = None
    previous_key = None
    result = record["sessions"]
    try:
        stage("key_material_load_begin")
        pk = (OUT / "public.bin").read_bytes()
        sk = bytearray((OUT / "private.bin").read_bytes())
        pin = bytes.fromhex((OUT / "public.sha256").read_text().strip())
        if hashlib.sha256(pk).digest() != pin or sk[768:1568] != pk:
            raise ValueError("pinned G6 test key mismatch")
        stage("key_material_load_complete")
        if not args.no_jtag:
            record["jtag_started"] = True
            write_result(record_path, record)
            stage("jtag_begin")
            jtag(args.workspace.resolve(), pk, sk, args.tool_root.resolve())
            record["jtag_completed"] = True
            write_result(record_path, record)
            stage("jtag_complete")
        stage("kem_init_begin")
        session = HostSession(pk, pin, Kem())
        stage("kem_init_complete")
        stage("cdc_enumeration_begin")
        device = port(args.wait_cdc)
        stage("cdc_enumeration_complete")
        ser = serial.Serial(port=None, baudrate=115200, timeout=0.25,
                            write_timeout=1.0 if args.bounded_control_write else None)
        ser.dtr = False
        ser.port = device
        for attempt in range(20):
            try:
                stage("serial_open_begin")
                ser.open()
                stage("serial_open_complete")
                break
            except serial.SerialException:
                if attempt == 19:
                    raise
                time.sleep(0.5)  # Windows may publish COM before CDC is ready to configure.
        stage("input_reset_begin")
        ser.reset_input_buffer()
        stage("input_reset_complete")
        stage("dtr_high_begin")
        ser.dtr = True
        stage("dtr_high_complete")
        decoder = UsbRecordDecoder()
        if args.fault_check:
            handshake(ser, decoder, session, bad_finished=True, debug_stage=args.debug_stage)
            if ser.read(1):
                raise RuntimeError("video sent after invalid host Finished")
            ser.dtr = False
            time.sleep(0.2)
            ser.reset_input_buffer()
            ser.dtr = True
            session.close("ERROR")
            decoder = UsbRecordDecoder()
        for index in range(args.sessions):
            handshake(ser, decoder, session, debug_stage=args.debug_stage)
            current_key = bytearray(session.video_key)
            key_changed = None if previous_key is None else not hmac.compare_digest(
                previous_key, current_key)
            if key_changed is False:
                raise RuntimeError("fresh G6 handshake repeated the prior video key")
            if args.report_key_fingerprint:
                session_record = {
                    "session_id": session.session_id,
                    "video_key_sha256": hashlib.sha256(current_key).hexdigest(),
                    "key_changed": key_changed,
                    "capture_directory": str(output / f"session_{index+1}"),
                }
                result.append(session_record)
                write_result(record_path, record)
                print(f"G6_SESSION_ESTABLISHED session_id={session.session_id} "
                      f"video_key_sha256={session_record['video_key_sha256']}", flush=True)
                def persist_verified_frames(count, byte_count, counters):
                    session_record["observed_verified_frames"] = count
                    session_record["observed_verified_bytes"] = byte_count
                    session_record["observed_statistics"] = dict(sorted(counters.items()))
                    if count <= 2:
                        hashes = session_record.setdefault("verified_frame_sha256", [])
                        hashes.append(hashlib.sha256(Path(session_record["capture_directory"],
                                                          "first.jpg" if count == 1 else "last.jpg").read_bytes()).hexdigest())
                    write_result(record_path, record)

                session_record.update(frames(ser, decoder, session, args.seconds,
                                             Path(session_record["capture_directory"]), args.show,
                                             on_verified_frame=persist_verified_frames))
            else:
                result.append(frames(ser, decoder, session, args.seconds,
                                     output / f"session_{index+1}", args.show))
            require_minimum_frames(result[-1])
            result[-1]['key_changed'] = key_changed
            if previous_key is not None:
                previous_key[:] = bytes(len(previous_key))
            previous_key = current_key
            kind = MessageType.REKEY if index + 1 < args.sessions else MessageType.STOP
            if index + 1 < args.sessions and args.reconnect:
                ser.dtr = False
                time.sleep(0.2)
                ser.reset_input_buffer()
                ser.dtr = True
                session.close("ERROR")
                decoder = UsbRecordDecoder()
            else:
                if kind == MessageType.STOP:
                    stage("stop_and_drain_begin")
                    stop_and_drain(ser, decoder, session, enabled=args.drain_stop)
                    stage("stop_and_drain_complete")
                else:
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
                stage("dtr_low_begin")
                ser.dtr = False
                stage("serial_close_begin")
                ser.close()
                stage("serial_close_complete")
            except (serial.SerialException, OSError):
                pass
        if previous_key is not None:
            previous_key[:] = bytes(len(previous_key))
        if sk is not None:
            sk[:] = bytes(len(sk))
        if session is not None:
            session.close()
        write_result(record_path, record)
        if stack_dump is not None:
            faulthandler.cancel_dump_traceback_later()
            stack_dump.close()
    print(f"G6_USB_OK port={device} sessions={len(result)} "
          f"fps={[round(x['fps'], 3) for x in result]} "
          f"fault_check={args.fault_check} reconnect={args.reconnect} output={output}")


if __name__ == "__main__":
    main()
