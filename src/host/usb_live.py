"""Receive and validate live G4 OV5640 JPEG frames over USB CDC."""
import argparse
from datetime import datetime
from io import BytesIO
from pathlib import Path
import secrets
import time

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from PIL import Image
import serial
from serial.tools import list_ports

from protocol import USB_VIDEO, UsbRecordDecoder, decode_video, make_nonce

G5_TEST_KEY = bytes.fromhex("00112233445566778899aabbccddeeff")


def decrypt_g5_packet(record, epoch):
    header, aad, ciphertext, tag = decode_video(record)
    if header.flags != 1 or header.session_id != 0:
        raise ValueError("invalid G5 test packet")
    return header, AESGCM(G5_TEST_KEY).decrypt(
        make_nonce(epoch, header.packet_sequence), ciphertext + tag, aad)


def receive(seconds, output, show=False, encrypted_test=False, tamper_check=False):
    ports = [p for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
    if len(ports) != 1:
        raise RuntimeError("Expected exactly one experimental EYEPQC CDC device")
    serial_port = serial.Serial(port=None, baudrate=115200, timeout=0.25)
    serial_port.dtr = False
    serial_port.port = ports[0].device
    serial_port.open()
    decoder = UsbRecordDecoder()
    frame = bytearray()
    expected_id = expected_seq = None
    first = last = start = None
    frames = total = 0
    tamper_checked = False
    window = None
    if show:
        import tkinter as tk
        from PIL import ImageTk
        window = tk.Tk()
        window.title("EYEPQC G4 USB live")
        label = tk.Label(window)
        label.pack()
    try:
        serial_port.reset_input_buffer()
        serial_port.dtr = True
        epoch = secrets.randbits(32) if encrypted_test else None
        command = b"E" + epoch.to_bytes(4, "big") if encrypted_test else b"V"
        if serial_port.write(command) != len(command):
            raise RuntimeError("incomplete USB start command")
        serial_port.flush()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for channel, record in decoder.feed(serial_port.read(16384)):
                if channel != USB_VIDEO:
                    raise ValueError("unexpected USB channel")
                if encrypted_test:
                    if tamper_check and not tamper_checked:
                        altered = record[:-1] + bytes([record[-1] ^ 1])
                        try:
                            decrypt_g5_packet(altered, epoch)
                        except InvalidTag:
                            tamper_checked = True
                        else:
                            raise RuntimeError("tampered board packet was accepted")
                    header, payload = decrypt_g5_packet(record, epoch)
                else:
                    header, _, payload, tag = decode_video(record, allow_plaintext=True)
                    if header.flags or header.session_id or tag:
                        raise ValueError("invalid G4 plaintext record")
                if header.jpeg_length > 65536:
                    raise ValueError("invalid G4 video record")
                if header.packet_id == 0:
                    if frame or (expected_id is not None and header.frame_id != expected_id):
                        raise ValueError("dropped or reordered frame")
                    frame = bytearray()
                    frame_length = header.jpeg_length
                    packet_count = header.packet_count
                    timestamp = header.timestamp
                elif (not frame or header.frame_id != expected_id - 1 or
                      header.jpeg_length != frame_length or
                      header.packet_count != packet_count or header.timestamp != timestamp):
                    raise ValueError("inconsistent JPEG fragment")
                if header.packet_id != len(frame) // 1400 or (
                    expected_seq is not None and header.packet_sequence != expected_seq
                ):
                    raise ValueError("dropped or reordered packet")
                expected_seq = header.packet_sequence + 1
                expected_id = (header.frame_id + 1) & 0xffffffff
                frame.extend(payload)
                if header.packet_id + 1 != header.packet_count:
                    continue
                if len(frame) != frame_length or frame[:2] != b"\xff\xd8" or frame[-2:] != b"\xff\xd9":
                    raise ValueError("invalid assembled JPEG")
                with Image.open(BytesIO(frame)) as image:
                    image.load()
                    if image.size != (640, 480):
                        raise ValueError("unexpected camera resolution")
                    if window:
                        photo = ImageTk.PhotoImage(image)
                        label.configure(image=photo)
                        label.image = photo
                        window.update()
                now = time.perf_counter()
                if start is None:
                    start = now
                    first = bytes(frame)
                last = bytes(frame)
                frames += 1
                total += len(frame)
                frame.clear()
        if frames < 2:
            raise RuntimeError("insufficient complete frames")
        if tamper_check and not tamper_checked:
            raise RuntimeError("no real board packet passed the tamper check")
    finally:
        serial_port.dtr = False
        serial_port.close()
        if window:
            window.destroy()
    output.mkdir(parents=True, exist_ok=False)
    (output / "first.jpg").write_bytes(first)
    (output / "last.jpg").write_bytes(last)
    elapsed = now - start
    print(f"{'G5' if encrypted_test else 'G4'}_USB_OK port={ports[0].device} "
          f"frames={frames} bytes={total} "
          f"elapsed_s={elapsed:.3f} fps={(frames-1)/elapsed:.3f} "
          f"trailing_partial={bool(frame or decoder.buffer)} "
          f"tamper_rejected={tamper_checked} output={output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--encrypted-test", action="store_true", help="G5 public fixed-key test mode")
    parser.add_argument("--tamper-check", action="store_true", help="Reject one corrupted real G5 packet copy")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    if args.tamper_check and not args.encrypted_test:
        parser.error("--tamper-check requires --encrypted-test")
    prefix = "g5_usb_" if args.encrypted_test else "g4_usb_"
    output = args.output or Path("data/captures") / (prefix + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    receive(args.seconds, output.resolve(), args.show, args.encrypted_test, args.tamper_check)


if __name__ == "__main__":
    main()
