"""G2 board acceptance: DDR -> DMA -> PL AES-GCM -> DMA -> DDR via volatile JTAG."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
LENGTHS = (*range(18), 31, 32, 1400)
MAGIC = 0x32474345


def vectors():
    for index, length in enumerate(LENGTHS):
        aad_length = (0, 1, 15, 16, 17, 64)[index % 6]
        key = hashlib.sha256(f"G2 key {index}".encode()).digest()[:16]
        nonce = hashlib.sha256(f"G2 nonce {index}".encode()).digest()[:12]
        aad = hashlib.shake_256(f"G2 aad {index}".encode()).digest(aad_length)
        plain = hashlib.shake_256(f"G2 plain {index}".encode()).digest(length)
        yield length, key, nonce, aad, plain


def check_manifest(workspace):
    manifest = json.loads((workspace / "build_manifest.json").read_text())
    for path, digest in manifest["sources"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("Build source changed: " + path)
    for path, digest in manifest["artifacts"].items():
        if hashlib.sha256((workspace / path).read_bytes()).hexdigest() != digest:
            raise ValueError("Build artifact changed: " + path)
    if hashlib.sha256(Path(manifest["xsa"]).read_bytes()).hexdigest() != manifest["xsa_sha256"]:
        raise ValueError("XSA changed")
    for name, size in (("g2_job", 192), ("g2_tx", 1472), ("g2_rx", 1536)):
        item = manifest["owned"][name]
        address = item["address"]
        if item["size"] != size or address % 64 or not 0x100000 <= address <= 0x40000000-size:
            raise ValueError("Invalid ELF-owned DDR address: " + name)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--boot", action="store_true", help="Volatile JTAG bitstream/ELF load on first job")
    parser.add_argument("--tool-root", type=Path, default=Path("D:/AmdDesignTools/2026.1"))
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    manifest = check_manifest(workspace)
    owned = manifest["owned"]
    target = ROOT / "data/captures" / ("g2_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    target.mkdir(parents=True)
    records = []
    for index, (length, key, nonce, aad, plain) in enumerate(vectors()):
        case = target / f"case_{index:02d}_{length}"
        case.mkdir()
        sealed = AESGCM(key).encrypt(nonce, plain, aad)
        request = (struct.pack("<8I", MAGIC, 0, length, len(aad), 0, 0, 0, 0) +
                   key + nonce + aad.ljust(64, b"\0") + bytes(16) +
                   struct.pack("<4I", owned["g2_tx"]["address"], owned["g2_rx"]["address"], 0, 0) +
                   bytes(36))
        if len(request) != 192: raise AssertionError("mailbox ABI")
        payload = plain.ljust(max(4, (length + 3) // 4 * 4), b"\0")
        request_path, payload_path = case / "request.bin", case / "plaintext.bin"
        reply_path, output_path = case / "reply.bin", case / "output.ddr"
        request_path.write_bytes(request)
        payload_path.write_bytes(payload)
        call = [str(args.tool_root / "Vivado/bin/xsdb.bat"), str(ROOT / "prj/run_g2_jtag.tcl"),
                str(workspace), str(int(args.boot and index == 0)),
                str(owned["g2_job"]["address"]), str(owned["g2_tx"]["address"]),
                str(owned["g2_rx"]["address"]), str(request_path), str(payload_path),
                str(reply_path), str(output_path), "30000"]
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
                raise RuntimeError(f"XSDB timed out; see {case}")
        (case / "xsdb.log").write_text(stdout + stderr)
        if process.returncode or "G2_JOB_DONE" not in stdout:
            raise RuntimeError(f"XSDB failed on case {index}; see {case / 'xsdb.log'}")
        reply = reply_path.read_bytes()
        if len(reply) != 192: raise RuntimeError("Truncated mailbox")
        values = struct.unpack_from("<8I", reply)
        magic, state, job_length, aad_length, status, actual, elapsed_us, packet_count = values
        if (magic, state, job_length, aad_length, status, actual, packet_count) != (
            MAGIC, 2, length, len(aad), 0, length+16, index+1):
            raise RuntimeError(f"Board status mismatch case {index}: {values}")
        if reply[32:124] != bytes(92): raise RuntimeError("Board did not clear Key/Nonce/AAD")
        if reply[124:140] != sealed[-16:]: raise RuntimeError("Tag register mismatch")
        if struct.unpack_from("<2I", reply, 140) != (owned["g2_tx"]["address"],
                                                       owned["g2_rx"]["address"]):
            raise RuntimeError("ELF-owned buffer address mismatch")
        output = output_path.read_bytes()[:length+16]
        if output != sealed or AESGCM(key).decrypt(nonce, output, aad) != plain:
            raise RuntimeError(f"DDR ciphertext/Tag mismatch case {index}")
        records.append(dict(case=index, length=length, aad_length=len(aad),
                            elapsed_us=elapsed_us, packet_count=packet_count,
                            sha256=hashlib.sha256(output).hexdigest()))
        print(f"G2_CASE_OK {index} length={length} aad={len(aad)} us={elapsed_us}")
    summary = dict(workspace=str(workspace), bit_sha256=manifest["artifacts"][
        "g2_crypto/_ide/bitstream/m01.bit"], cases=records, board_validated=True)
    (target / "result.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("G2_BOARD_OK", target)


if __name__ == "__main__":
    main()
