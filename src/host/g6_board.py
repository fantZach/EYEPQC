"""Development G6: JTAG seed/key provision, USB ML-KEM handshake, live AES-GCM JPEG."""
import argparse
from datetime import datetime
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

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


def port():
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        found = [p for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
        if len(found) == 1:
            return found[0].device
        time.sleep(0.2)
    raise RuntimeError("G6 USB CDC device not found")


def send_control(ser, message):
    record = encode_usb_record(USB_CONTROL, message)
    if ser.write(record) != len(record):
        raise RuntimeError("incomplete USB control write")
    ser.flush()


def read_control(ser, decoder):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        records = decoder.feed(ser.read(4096))
        if records:
            if len(records) != 1 or records[0][0] != USB_CONTROL:
                raise ValueError("unexpected response during handshake")
            decode_control(records[0][1])
            return records[0][1]
    raise TimeoutError("G6 control response timeout")


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
    frame_id = sequence = 0
    total = count = 0
    first = last = started = ended = None
    next_report = time.perf_counter() + 300
    aes = AESGCM(bytes(session.video_key))
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for channel, record in decoder.feed(ser.read(16384)):
                if channel != USB_VIDEO:
                    raise ValueError("unexpected G6 USB channel")
                h, aad, ciphertext, tag = decode_video(record)
                if h.flags != 1 or h.session_id != session.session_id or h.jpeg_length > 65536:
                    raise ValueError("invalid G6 video header")
                payload = aes.decrypt(make_nonce(session.epoch, h.packet_sequence),
                                      ciphertext + tag, aad)
                if not session.accept_authenticated_packet(h.session_id, h.packet_sequence):
                    raise ValueError("replayed authenticated G6 packet")
                if h.packet_sequence != sequence or h.frame_id != frame_id:
                    raise ValueError("missing G6 packet or frame")
                if h.packet_id == 0:
                    if frame:
                        raise ValueError("missing fragment in prior frame")
                    frame_length, packet_count, timestamp = h.jpeg_length, h.packet_count, h.timestamp
                elif (not frame or h.jpeg_length != frame_length or
                      h.packet_count != packet_count or h.timestamp != timestamp):
                    raise ValueError("inconsistent G6 frame fragments")
                if h.packet_id != len(frame) // 1400:
                    raise ValueError("G6 fragment order mismatch")
                frame.extend(payload)
                sequence += 1
                if h.packet_id + 1 != h.packet_count:
                    continue
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
                ended = time.perf_counter()
                if started is None:
                    started = ended
                    first = bytes(frame)
                last = bytes(frame)
                total += len(frame)
                count += 1
                frame_id += 1
                frame.clear()
                if ended >= next_report:
                    print(f"G6_PROGRESS frames={count} fps={(count-1)/(ended-started):.3f}",
                          flush=True)
                    next_report = ended + 300
    finally:
        if window:
            window.destroy()
    if count < 2:
        raise RuntimeError("insufficient authenticated G6 frames")
    output.mkdir(parents=True)
    (output / "first.jpg").write_bytes(first)
    (output / "last.jpg").write_bytes(last)
    elapsed = ended - started
    return dict(frames=count, bytes=total, seconds=elapsed,
                fps=(count - 1) / elapsed, output=str(output),
                session_id=session.session_id, packets=sequence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT / "build/vitis/software_ready")
    parser.add_argument("--tool-root", type=Path,
                        default=Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1")),
                        help="AMD tools install root (or set EYEPQC_TOOL_ROOT)")
    parser.add_argument("--no-jtag", action="store_true",
                        help="reuse an already provisioned, running board")
    parser.add_argument("--verify-only", action="store_true",
                        help="check build hashes without JTAG, USB or reading test private keys")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--sessions", type=int, default=2)
    parser.add_argument("--fault-check", action="store_true",
                        help="reject a tampered Finished, then reconnect")
    parser.add_argument("--reconnect", action="store_true",
                        help="drop DTR between sessions instead of authenticated REKEY")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    if args.seconds <= 0 or not 1 <= args.sessions <= 3:
        parser.error("seconds must be positive and sessions 1..3")
    manifest, checked = verify_build(args.workspace, 'g6_usb_manifest.json')
    if manifest.get('application') != 'g6_usb':
        raise ValueError('Expected a G6 firmware manifest')
    if args.verify_only:
        print(f'G6_PREFLIGHT_OK hashes={checked} board_accessed=false')
        return
    pk = (OUT / "public.bin").read_bytes()
    sk = (OUT / "private.bin").read_bytes()
    pin = bytes.fromhex((OUT / "public.sha256").read_text().strip())
    if hashlib.sha256(pk).digest() != pin or sk[768:1568] != pk:
        raise ValueError("pinned G6 test key mismatch")
    if not args.no_jtag:
        jtag(args.workspace.resolve(), pk, sk, args.tool_root.resolve())
    device = port()
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
    session = HostSession(pk, pin, Kem())
    result = []
    output = (ROOT / "data/captures" /
              ("g6_usb_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))).resolve()
    try:
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
            result.append(frames(ser, decoder, session, args.seconds,
                                 output / f"session_{index+1}", args.show))
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
                time.sleep(0.2)
                ser.reset_input_buffer()
                decoder = UsbRecordDecoder()
    finally:
        ser.dtr = False
        ser.close()
        session.close()
    (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"G6_USB_OK port={device} sessions={len(result)} "
          f"fps={[round(x['fps'], 3) for x in result]} "
          f"fault_check={args.fault_check} reconnect={args.reconnect} output={output}")


if __name__ == "__main__":
    main()
