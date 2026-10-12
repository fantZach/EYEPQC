"""Validate PS USB0 fixed v1 plaintext video records over the real CDC link."""
import argparse
from pathlib import Path
import sys
import time

import serial
from serial.tools import list_ports

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pc/src/host"))
from protocol import USB_VIDEO, UsbRecordDecoder, decode_video

PATTERN = bytes(range(256))
MARKER = b"\x02\x05\xa0"  # channel 2, record_length 1440


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=5)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("seconds must be positive")
    ports = [p for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
    if len(ports) != 1:
        raise SystemExit("Expected one USB probe CDC device")
    ser = serial.Serial(port=None, baudrate=115200, timeout=3)
    ser.dtr = False
    ser.port = ports[0].device
    ser.open()
    try:
        ser.reset_input_buffer()
        ser.dtr = True
        ser.write(b"R")
        ser.flush()
        t0 = time.monotonic()
        parts = []
        while time.monotonic() - t0 < args.seconds:
            part = ser.read(1 << 20)
            if not part:
                raise RuntimeError("USB record stream stalled")
            parts.append(part)
        elapsed = time.monotonic() - t0
        ser.dtr = False
    finally:
        ser.close()
    raw = b"".join(parts)
    start = raw.find(MARKER)
    if start < 0:
        raise RuntimeError("No USB record marker")
    decoder = UsbRecordDecoder()
    records = []
    for offset in range(start, len(raw), 65536):
        records.extend(decoder.feed(raw[offset:offset + 65536]))
    first = last = None
    for channel, record in records:
        if channel != USB_VIDEO:
            raise RuntimeError("Wrong USB channel")
        header, _, payload, tag = decode_video(record, allow_plaintext=True)
        if (header.flags != 0 or header.packet_id != 0 or header.packet_count != 1 or
            header.jpeg_length != 1400 or tag):
            raise RuntimeError("Invalid test video header")
        seq = header.packet_sequence
        if header.frame_id != (seq & 0xffffffff) or (last is not None and seq != last + 1):
            raise RuntimeError(f"Dropped or reordered USB record: {last} -> {seq}")
        rotated = PATTERN[seq & 255:] + PATTERN[:seq & 255]
        if payload != (rotated * 6)[:1400]:
            raise RuntimeError(f"Corrupt USB payload at sequence {seq}")
        if first is None:
            first = seq
        last = seq
    if not records:
        raise RuntimeError("No complete USB records")
    print(f"M11_FIXED_USB_OK port={ports[0].device} seconds={elapsed:.3f} "
          f"records={len(records)} first={first} last={last} "
          f"received_MBps={len(raw)/elapsed/1_000_000:.3f}")


if __name__ == "__main__":
    main()
