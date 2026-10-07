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


def decrypt_g3(frame_length, sealed, key, prefix, nonce_start=0):
    if not 4 <= frame_length <= 65536:
        raise ValueError("Invalid captured JPEG length")
    chunks = (frame_length + CHUNK - 1) // CHUNK
    if len(key) != 16 or len(prefix) != 8 or not 0 <= nonce_start <= (1 << 32) - chunks:
        raise ValueError("Invalid G3 key or nonce")
    if len(sealed) != frame_length + 16 * chunks:
        raise ValueError("Encrypted packet length mismatch")
    aes = AESGCM(key)
    rebuilt = bytearray()
    cursor = 0
    for index in range(chunks):
        offset = index * CHUNK
        size = min(CHUNK, frame_length - offset)
        aad = struct.pack(">4I", frame_length, offset, index, chunks)
        nonce = prefix + (nonce_start + index).to_bytes(4, "big")
        part = sealed[cursor:cursor + size + 16]
        rebuilt.extend(aes.decrypt(nonce, part, aad))
        cursor += size + 16
    frame = bytes(rebuilt)
    if frame[:2] != b"\xff\xd8" or frame[-2:] != b"\xff\xd9":
        raise ValueError("Decrypted data is not JPEG")
    return frame


def verify(frame, sealed, key, prefix, nonce_start=0):
    if decrypt_g3(len(frame), sealed, key, prefix, nonce_start) != frame:
        raise ValueError("Decrypted JPEG differs from captured DDR bytes")
    return (len(frame) + CHUNK - 1) // CHUNK


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--boot", action="store_true", help="Volatile bitstream/ELF load on first frame")
    parser.add_argument("--count", type=int, default=1, help="Number of separate board jobs")
    parser.add_argument("--frames-per-run", type=int, default=1,
                        help="Frames captured/encrypted continuously in one board job")
    parser.add_argument("--size", choices=("320x240", "640x480"), default="320x240")
    parser.add_argument("--quality", type=int, default=12)
    parser.add_argument("--vts", type=int, help="Camera frame lines; defaults to 1000 in fast mode")
    parser.add_argument("--fast", action="store_true", help="Low-resolution subsampling mode")
    parser.add_argument("--tool-root", type=Path,
                        default=Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1")))
    args = parser.parse_args()
    vts = args.vts if args.vts is not None else (1000 if args.fast else 1968)
    if (not 1 <= args.count <= 100 or not 1 <= args.frames_per_run <= 1000 or
        not 0 <= args.quality <= 63 or not 1000 <= vts <= 5000):
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
    sensor_cfg = vts << 9 | args.quality << 3 | (4 if args.size == "640x480" else 0) | 2
    if args.fast: sensor_cfg |= 1 << 25
    target = ROOT / "data/captures" / ("g3_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    target.mkdir(parents=True)
    records = []
    used = set()
    timeout_ms = max(30000, args.frames_per_run * 400 + 30000)
    for index in range(args.count):
        case = target / f"frame_{index:03d}"
        case.mkdir()
        key, prefix = secrets.token_bytes(16), secrets.token_bytes(8)
        if (key, prefix) in used: raise RuntimeError("Repeated test nonce/key pair")
        used.add((key, prefix))
        request = (struct.pack("<16I", MAGIC, 0, sensor_cfg, *([0] * 13)) + key + prefix +
                   struct.pack("<10I", args.frames_per_run, *([0] * 9)))
        request_path = case / "request.bin"
        request_path.write_bytes(request)
        reply_path, jpeg_path, sealed_path = case / "reply.bin", case / "frame.jpg", case / "packets.enc"
        call = [str(args.tool_root / "Vivado/bin/xsdb.bat"), str(ROOT / "prj/run_g3_jtag.tcl"),
                str(workspace), str(int(args.boot and index == 0)),
                str(owned["g3_job"]["address"]), str(owned["g3_frame"]["address"]),
                str(owned["g3_sealed"]["address"]), str(request_path), str(reply_path),
                str(jpeg_path), str(sealed_path), str(timeout_ms)]
        with subprocess.Popen(call, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout_ms / 1000 + 180)
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
            detail = (stdout + stderr).strip()[-3000:]
            raise RuntimeError(f"XSDB failed on frame {index}; see {case / 'xsdb.log'}\n{detail}")
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
        (requested, completed, total_bytes, dropped, overflows, queued, sent,
         capture_us, encrypt_us, nonce_start) = struct.unpack_from("<10I", reply, 88)
        if len(frame) != length or len(sealed) != sealed_length or verify(
            frame, sealed, key, prefix, nonce_start) != chunks:
            raise RuntimeError(f"Frame {index} failed authenticated roundtrip")
        if (requested != args.frames_per_run or completed != requested or
            total_bytes < length or not 0 < elapsed_us <= timeout_ms * 1000 or
            not 0 < pclk_hz <= 72000000 or nonce_start + chunks > 47000):
            raise RuntimeError("Invalid camera/timer witness")
        if not (cap_status & 0x1000) or not (tx_status & 0x1000) or not (rx_status & 0x1000):
            raise RuntimeError("DMA completion status missing")
        if records and packet_count != records[-1]["packet_count"] + nonce_start + chunks:
            raise RuntimeError("GCM packet count did not advance")
        if sent != completed or queued < sent:
            raise RuntimeError("Camera sent/queued counters disagree with completed frames")
        records.append(dict(job=index, frames=completed, length=length, chunks=chunks,
                            sealed_length=sealed_length, elapsed_us=elapsed_us,
                            fps=round(completed * 1_000_000 / elapsed_us, 3),
                            total_bytes=total_bytes, dropped=dropped, overflows=overflows,
                            queued=queued, sent=sent, capture_us=capture_us,
                            encrypt_us=encrypt_us, nonce_start=nonce_start,
                            pclk_hz=pclk_hz, packet_count=packet_count,
                            jpeg_sha256=hashlib.sha256(frame).hexdigest()))
        print(f"G3_RUN_OK {index} frames={completed} fps={records[-1]['fps']} "
              f"dropped={dropped} overflows={overflows} last_jpeg={length}")
    result = dict(workspace=str(workspace), fast=args.fast, vts=vts,
        bit_sha256=manifest["artifacts"][
        "g3_camera/_ide/bitstream/m01.bit"], runs=records,
        board_validated=all(not x["dropped"] and not x["overflows"] for x in records))
    (target / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    if not result["board_validated"]:
        raise RuntimeError(f"Camera drops/overflows recorded; see {target / 'result.json'}")
    print("G3_BOARD_OK", target)


if __name__ == "__main__":
    main()
