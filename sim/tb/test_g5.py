"""G5 host authentication fails closed on tampering and plaintext downgrade."""
from pathlib import Path
import sys
import unittest

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src/host"))
from protocol import encode_video, make_nonce, packet_header
from usb_live import G5_TEST_KEY, decrypt_g5_packet


class G5(unittest.TestCase):
    def test_packet_authentication(self):
        epoch = 0x10203040
        header = packet_header(0, 8, 4, 0, 1234, 23)
        plaintext = b"\xff\xd8\xff\xd9"
        sealed = AESGCM(G5_TEST_KEY).encrypt(
            make_nonce(epoch, header.packet_sequence), plaintext, header.pack())
        packet = encode_video(header, sealed[:-16], sealed[-16:])
        got, decoded = decrypt_g5_packet(packet, epoch)
        self.assertEqual((got, decoded), (header, plaintext))
        tampered = bytearray(packet)
        tampered[-1] ^= 1
        with self.assertRaises(InvalidTag):
            decrypt_g5_packet(bytes(tampered), epoch)
        with self.assertRaises(InvalidTag):
            decrypt_g5_packet(packet, epoch + 1)
        with self.assertRaises(ValueError):
            decrypt_g5_packet(encode_video(packet_header(0, 8, 4, 0, 1234, 23,
                                                       encrypted=False), plaintext), epoch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
