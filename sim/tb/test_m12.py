"""M12 offline replay: python sim/tb/test_m12.py"""
from io import BytesIO
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc/src/host"))
from g3_board import CHUNK, MAGIC, decrypt_g3
from protocol import USB_VIDEO, UsbRecordDecoder, encode_usb_record
from receiver import replay_frame


class M12(unittest.TestCase):
    def test_usb_record_boundaries(self):
        wire = encode_usb_record(USB_VIDEO, b"jpeg") + encode_usb_record(USB_VIDEO, b"next")
        decoder = UsbRecordDecoder()
        output = []
        for byte in wire:
            output.extend(decoder.feed(bytes([byte])))
        decoder.finish()
        self.assertEqual(output, [(USB_VIDEO, b"jpeg"), (USB_VIDEO, b"next")])
        with self.assertRaises(ValueError):
            decoder.feed(b"\x02\xff\xff")
        self.assertEqual(decoder.buffer, b"")
        decoder.feed(wire[:2])
        with self.assertRaises(ValueError):
            decoder.finish()

    def test_real_jpeg_roundtrip_and_rejections(self):
        image = Image.frombytes("RGB", (100, 100), random.Random(7).randbytes(30000))
        encoded = BytesIO()
        image.save(encoded, format="JPEG")
        frame = encoded.getvalue()
        self.assertGreater(len(frame), CHUNK)
        key, prefix = bytes(range(16)), bytes(range(16, 24))
        count = (len(frame) + CHUNK - 1) // CHUNK
        sealed = b"".join(AESGCM(key).encrypt(prefix + i.to_bytes(4, "big"),
            frame[i*CHUNK:(i+1)*CHUNK], struct.pack(">4I", len(frame), i*CHUNK, i, count))
            for i in range(count))
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            request = struct.pack("<16I", MAGIC, *([0] * 15)) + key + prefix + bytes(40)
            reply = bytearray(128)
            struct.pack_into("<7I", reply, 0, MAGIC, 2, 0, 0, len(frame), count, len(sealed))
            (folder / "request.bin").write_bytes(request)
            (folder / "reply.bin").write_bytes(reply)
            (folder / "packets.enc").write_bytes(sealed)
            (folder / "frame.jpg").write_bytes(frame)
            recovered, size = replay_frame(folder)
            self.assertEqual((recovered, size), (frame, (100, 100)))
            tampered = bytearray(sealed)
            tampered[CHUNK + 3] ^= 1
            (folder / "packets.enc").write_bytes(tampered)
            with self.assertRaises(InvalidTag):
                replay_frame(folder)
            (folder / "packets.enc").write_bytes(sealed[:-1])
            with self.assertRaises(ValueError):
                replay_frame(folder)
            with self.assertRaises(ValueError):
                decrypt_g3(len(frame), sealed, key, prefix, (1 << 32) - count + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
