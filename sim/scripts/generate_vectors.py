"""Generate byte-reproducible M00 data; all keys here are public TEST KEYS."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc" / "src" / "host"))
from crypto_ref import encrypt, ghash_trace, mlkem_vector
from protocol import packet_header, make_nonce

LENGTHS = (0, 1, 15, 16, 17, 31, 32, 1400)


def test_bytes(label, size):
    return hashlib.shake_256(b"EYEPQC M00 TEST ONLY v1:" + label.encode()).digest(size)


def build_vectors():
    vectors = []
    for length in LENGTHS:
        for aad_length in (0, 1, 15, 16, 17, 40, 64):
            name = f"boundary_{length}_aad_{aad_length}"
            vectors.append(gcm_vector(name, length, aad_length))
    for index in range(24):
        name = f"random_{index:02}"
        length = int.from_bytes(test_bytes(name + ":length", 2), "big") % 1401
        vectors.append(gcm_vector(name, length, test_bytes(name + ":aadlen", 1)[0] % 65))
    tamper = []
    for vector in vectors:
        if not vector["name"].startswith("boundary_") or len(vector["aad"]) != 80:
            continue
        for field in ("key", "nonce", "aad", "ciphertext", "tag"):
            raw = bytes.fromhex(vector[field])
            if not raw:
                continue
            changed = bytes([raw[0] ^ 1]) + raw[1:]
            tamper.append({"base": vector["name"], "field": field,
                           "replacement": changed.hex(), "expected": "InvalidTag"})
    packets = []
    for packet_id, sequence, length in ((0, 0, 1400), (1, 1, 1)):
        header = packet_header(0x01020304, 0x05060708, 1401, packet_id,
                               0x0102030405060708, sequence)
        key = test_bytes("wire_key", 16)
        nonce = make_nonce(0x11223344, sequence)
        plaintext = test_bytes(f"wire_payload_{packet_id}", length)
        ct, tag = encrypt(key, nonce, plaintext, header.pack())
        packets.append({"header": header.pack().hex(), "key": key.hex(),
                        "session_epoch": 0x11223344, "nonce": nonce.hex(),
                        "plaintext": plaintext.hex(), "ciphertext": ct.hex(),
                        "tag": tag.hex(), "datagram": (header.pack() + ct + tag).hex()})
    return {
        "aes_gcm.json": {"schema": 1, "test_only": True, "vectors": vectors},
        "aes_gcm_tamper.json": {"schema": 1, "test_only": True, "vectors": tamper},
        "protocol.json": {"schema": 1, "test_only": True, "packets": packets},
        "mlkem512.json": {"schema": 1, "test_only": True,
                          "backend": "kyber-py==1.2.0 (offline only)",
                          "vectors": [mlkem_vector(test_bytes(f"kem_seed_{i}", 64),
                                                   test_bytes(f"kem_m_{i}", 32))
                                      for i in range(3)]},
    }


def gcm_vector(name, length, aad_length):
    key, nonce = test_bytes(name + ":key", 16), test_bytes(name + ":nonce", 12)
    plaintext, aad = test_bytes(name + ":plaintext", length), test_bytes(name + ":aad", aad_length)
    ciphertext, tag = encrypt(key, nonce, plaintext, aad)
    trace = ghash_trace(key, nonce, aad, ciphertext)
    if trace["tag"] != tag.hex():
        raise RuntimeError(f"independent GHASH mismatch: {name}")
    return {"name": name, "key": key.hex(), "nonce": nonce.hex(), "aad": aad.hex(),
            "plaintext": plaintext.hex(), "ciphertext": ciphertext.hex(),
            "tag": tag.hex(), "ghash": trace}


def encoded_files():
    return {name: (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
            for name, data in build_vectors().items()}


def canonicalize_line_endings(data):
    return data.replace(b"\r\n", b"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "sim" / "vectors")
    parser.add_argument("--check", action="store_true", help="compare without writing")
    args = parser.parse_args()
    files = encoded_files()
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    files["sha256.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    if not args.check:
        args.output.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        path = args.output / name
        if args.check:
            if not path.is_file() or canonicalize_line_endings(path.read_bytes()) != data:
                raise SystemExit(f"not reproducible: {path}")
        else:
            path.write_bytes(data)
    print(f"{'Verified' if args.check else 'Generated'} {len(files)} reproducible vector files")


if __name__ == "__main__":
    main()
