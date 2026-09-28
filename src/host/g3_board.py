"""Capture real JPEG, authenticate/decrypt each PL GCM chunk, compare every byte."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
MAGIC = 0x33474345
CHUNK = 1400


def verify(frame, sealed, key, prefix):
    if not 4 <= len(frame) <= 65536 or frame[:2] != b"\xff\xd8" or frame[-2:] != b"\xff\xd9":
        raise ValueError("Invalid captured JPEG")
    chunks = (len(frame) + CHUNK - 1) // CHUNK
    if len(sealed) != len(frame) + 16 * chunks:
        raise ValueError("Encrypted packet length mismatch")
    aes = AESGCM(key)
    rebuilt = bytearray()
    cursor = 0
    for index in range(chunks):
        offset = index * CHUNK
        size = min(CHUNK, len(frame) - offset)
        aad = struct.pack(">4I", len(frame), offset, index, chunks)
        nonce = prefix + index.to_bytes(4, "big")
        part = sealed[cursor:cursor + size + 16]
        rebuilt.extend(aes.decrypt(nonce, part, aad))
        cursor += size + 16
    if rebuilt != frame:
        raise ValueError("Decrypted JPEG differs from captured DDR bytes")
    return chunks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--boot", action="store_true", help="Volatile bitstream/ELF load on first frame")
    parser.add_argument("--count", type=int, default=8, help="Real camera frames to validate")
    parser.add_argument("--size", choices=("320x240", "640x480"), default="320x240")
    parser.add_argument("--quality", type=int, default=12)
    parser.add_argument("--vts", type=int, default=1968)
    parser.add_argument("--tool-root", type=Path, default=Path("D:/AmdDesignTools/2026.1"))
    args = parser.parse_args()
    if not 1 <= args.count <= 100 or not 0 <= args.quality <= 63 or not 1000 <= args.vts <= 5000:
        parser.error("Invalid frame count or camera calibration")
    workspace = args.workspace.resolve()
    manifest = json.loads((workspace / "build_manifest.json").read_text())
    for path, digest in manifest["sources"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("Build source changed: " + path)
    for path, digest in manifest["artifacts"].items():
        if hashlib.sha256((workspace / path).read_bytes()).hexdigest() != digest:
            raise ValueError("Build artifact changed: " + path)
    if hashlib.sha256(Path(manifest["xsa"]).read_bytes()).hexdigest() != manifest["xsa_sha256"]:
        raise ValueError("XSA changed")
    owned = manifest["owned"]
    for name, size in (("g3_job", 128), ("g3_frame", 65600), ("g3_sealed", 68096)):
        item = owned[name]
        a = item["address"]
        if item["size"] != size or a % 64 or not 0x100000 <= a <= 0x40000000 - size:
            raise ValueError("Invalid ELF-owned DDR symbol: " + name)
    sensor_cfg = args.vts << 9 | args.quality << 3 | (4 if args.size == "640x480" else 0) | 2
    target = ROOT / "data/captures" / ("g3_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    target.mkdir(parents=True)
    records = []
    used = set()
    for index in range(args.count):
        case = target / f"frame_{index:03d}"
        case.mkdir()
        key, prefix = secrets.token_bytes(16), secrets.token_bytes(8)
        if (key, prefix) in used: raise RuntimeError("Repeated test nonce/key pair")
        used.add((key, prefix))
        request = struct.pack("<16I", MAGIC, 0, sensor_cfg, *([0] * 13)) + key + prefix + bytes(40)
        request_path = case / "request.bin"
        request_path.write_bytes(request)
        reply_path, jpeg_path, sealed_path = case / "reply.bin", case / "frame.jpg", case / "packets.enc"
        call = [str(args.tool_root / "Vivado/bin/xsdb.bat"), str(ROOT / "prj/run_g3_jtag.tcl"),
                str(workspace), str(int(args.boot and index == 0)),
                str(owned["g3_job"]["address"]), str(owned["g3_frame"]["address"]),
                str(owned["g3_sealed"]["address"]), str(request_path), str(reply_path),
                str(jpeg_path), str(sealed_path), "30000"]
        with subprocess.Popen(call, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            try:
                stdout, stderr = process.communicate(timeout=210 if index == 0 else 75)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
                else:
                    process.kill()
                stdout, stderr = process.communicate(timeout=30)
                (case / "xsdb.log").write_text(stdout + stderr + "\nHOST XSDB TIMEOUT\n")
                raise RuntimeError(f"XSDB timeout; see {case}")
        (case / "xsdb.log").write_text(stdout + stderr)
        if process.returncode or "G3_JOB_DONE" not in stdout:
            raise RuntimeError(f"XSDB failed on frame {index}; see {case / 'xsdb.log'}")
        reply = reply_path.read_bytes()
        if len(reply) != 128: raise RuntimeError("Truncated G3 mailbox")
        fields = struct.unpack_from("<16I", reply)
        (magic, state, cfg, status, length, chunks, sealed_length, elapsed_us,
         frame_address, sealed_address, camera_status, cap_status, tx_status,
         rx_status, pclk_hz, packet_count) = fields
        if (magic, state, cfg, status, frame_address, sealed_address) != (
            MAGIC, 2, sensor_cfg, 0, owned["g3_frame"]["address"], owned["g3_sealed"]["address"]):
            raise RuntimeError(f"Invalid G3 reply frame {index}: {fields}")
        if reply[64:88] != bytes(24): raise RuntimeError("G3 Key/Nonce not cleared")
        frame = jpeg_path.read_bytes()[:length]
        sealed = sealed_path.read_bytes()[:sealed_length]
        if len(frame) != length or len(sealed) != sealed_length or verify(frame, sealed, key, prefix) != chunks:
            raise RuntimeError(f"Frame {index} failed authenticated roundtrip")
        if not 0 < elapsed_us < 30000000 or not 0 < pclk_hz <= 72000000:
            raise RuntimeError("Invalid camera/timer witness")
        if not (cap_status & 0x1000) or not (tx_status & 0x1000) or not (rx_status & 0x1000):
            raise RuntimeError("DMA completion status missing")
        if records and packet_count != records[-1]["packet_count"] + chunks:
            raise RuntimeError("GCM packet count did not advance")
        records.append(dict(frame=index, length=length, chunks=chunks,
                            sealed_length=sealed_length, elapsed_us=elapsed_us,
                            pclk_hz=pclk_hz, packet_count=packet_count,
                            jpeg_sha256=hashlib.sha256(frame).hexdigest()))
        print(f"G3_FRAME_OK {index} jpeg={length} chunks={chunks} us={elapsed_us}")
    result = dict(workspace=str(workspace), bit_sha256=manifest["artifacts"][
        "g3_camera/_ide/bitstream/m01.bit"], frames=records, board_validated=True)
    (target / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print("G3_BOARD_OK", target)


if __name__ == "__main__":
    main()
