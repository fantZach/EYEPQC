"""Roundtrip a saved real JPEG through PS USB0, using v1 plaintext records."""
import argparse
from datetime import datetime
from io import BytesIO
from pathlib import Path
import struct
import sys
import time

from PIL import Image
import serial
from serial.tools import list_ports

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pc/src/host"))
from protocol import USB_VIDEO, UsbRecordDecoder, decode_video


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frame_folder", type=Path)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    folder = args.frame_folder.resolve()
    reply = (folder / "reply.bin").read_bytes()
    if len(reply) != 128:
        parser.error("Expected a G3 frame directory")
    length = struct.unpack_from("<I", reply, 16)[0]
    if not 4 <= length <= 65536:
        parser.error("Invalid source JPEG length")
    frame = (folder / "frame.jpg").read_bytes()[:length]
    if len(frame) != length or frame[:2] != b"\xff\xd8" or frame[-2:] != b"\xff\xd9":
        parser.error("Invalid source JPEG")
    ports = [p for p in list_ports.comports() if p.vid == 0x03FD and p.pid == 0x7020]
    if len(ports) != 1:
        raise SystemExit("Expected one USB probe CDC device")
    ser = serial.Serial(port=None, baudrate=115200, timeout=1)
    ser.dtr = False
    ser.port = ports[0].device
    ser.open()
    decoder = UsbRecordDecoder()
    rebuilt = bytearray()
    packet = 0
    expected_count = (length + 1399) // 1400
    try:
        ser.reset_input_buffer()
        ser.dtr = True
        sent = ser.write(b"J" + struct.pack("<I", length) + frame)
        if sent != length + 5:
            raise RuntimeError("USB JPEG write incomplete")
        ser.flush()
        deadline = time.monotonic() + 10
        while packet < expected_count and time.monotonic() < deadline:
            for channel, record in decoder.feed(ser.read(4096)):
                if channel != USB_VIDEO:
                    raise RuntimeError("Unexpected USB channel")
                header, _, payload, tag = decode_video(record, allow_plaintext=True)
                if (header.flags != 0 or header.session_id != 0 or header.frame_id != 0 or
                    header.jpeg_length != length or header.packet_count != expected_count or
                    header.packet_id != packet or header.packet_sequence != packet or tag):
                    raise RuntimeError(f"Invalid JPEG record at packet {packet}")
                rebuilt.extend(payload)
                packet += 1
        if packet != expected_count or rebuilt != frame:
            raise RuntimeError(f"USB JPEG mismatch: packets={packet}/{expected_count}")
    finally:
        ser.dtr = False
        ser.close()
    with Image.open(BytesIO(rebuilt)) as image:
        image.load()
        size = image.size
        if args.show:
            image.show()
    output = folder.parent / ("m11_usb_fixed_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".jpg")
    output.write_bytes(rebuilt)
    print(f"M11_USB_JPEG_OK port={ports[0].device} bytes={length} packets={packet} "
          f"size={size[0]}x{size[1]} output={output}")


if __name__ == "__main__":
    main()
