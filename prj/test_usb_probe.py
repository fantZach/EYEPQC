"""Validate the temporary CDC stream and measure sustained useful bytes/s."""
import argparse
import struct
import time
import serial
from serial.tools import list_ports

CHUNK = 16384
MAGIC = b"EYEP"
PATTERN = bytes(range(256))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=30)
    args = parser.parse_args()
    ports = [p for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
    if len(ports) != 1:
        raise SystemExit(f"Expected one USB probe COM port, found {[(p.device,p.hwid) for p in ports]}")
    ser = serial.Serial(port=None, baudrate=115200, timeout=3)
    ser.dtr = False
    ser.port = ports[0].device
    ser.open()
    try:
        ser.dtr = True
        ser.write(b"T")
        ser.flush()
        parts = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < args.seconds:
            part = ser.read(1 << 20)
            if not part:
                raise RuntimeError("USB stream stalled")
            parts.append(part)
        elapsed = time.monotonic() - t0
        ser.dtr = False
        raw = b"".join(parts)
        start = raw.find(MAGIC)
        if start < 0:
            raise RuntimeError("No stream marker")
        first = None
        last = None
        count = 0
        for offset in range(start, len(raw) - CHUNK + 1, CHUNK):
            block = raw[offset:offset + CHUNK]
            if block[:4] != MAGIC:
                raise RuntimeError(f"Lost block alignment at byte {offset}")
            seq = struct.unpack_from("<I", block, 4)[0]
            if last is not None and seq != last + 1:
                raise RuntimeError(f"Dropped/reordered block: {last} -> {seq}")
            rotated = PATTERN[seq & 255:] + PATTERN[:seq & 255]
            if block[8:] != (rotated * 64)[8:]:
                expected = (rotated * 64)[8:]
                offset = next(i for i, (a, b) in enumerate(zip(block[8:], expected), 8) if a != b)
                raise RuntimeError(f"Corrupt payload at block {seq}, byte {offset}: "
                                   f"got {block[offset]:02x}, expected {expected[offset-8]:02x}; "
                                   f"next marker at {block.find(MAGIC, 4)}")
            if first is None:
                first = seq
            last = seq
            count += 1
        rate = len(raw) / elapsed / 1_000_000
        print(f"USB_PROBE_OK port={ser.port} seconds={elapsed:.3f} blocks={count} "
              f"first={first} last={last} received_MBps={rate:.3f}")
    finally:
        ser.dtr = False
        ser.close()


if __name__ == "__main__":
    main()
