"""Run the M10 offline handshake against the A9 over JTAG (no Ethernet)."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import struct
import subprocess

from handshake import HostSession
from m09 import Kem, LIB, OUT as M09_OUT, PK, SK
from protocol import MessageType

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "board/output/m10"
JOB = struct.Struct("<8I56s44s12s32s80s")
COMMANDS = {"load": 1, "begin": 2, "finish": 3, "rekey": 4, "clear": 5}


def manifest_check(workspace):
    manifest = json.loads((workspace / "build_manifest.json").read_text())
    for path, digest in manifest["sources"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("M10 source changed after build: " + path)
    for name in ("elf", "xsa"):
        if hashlib.sha256(Path(manifest[name]).read_bytes()).hexdigest() != manifest[name + "_sha256"]:
            raise ValueError("M10 " + name + " changed after build")
    bit = workspace / "m10/_ide/bitstream/m01.bit"
    if hashlib.sha256(bit.read_bytes()).hexdigest() != manifest["bit_sha256"]:
        raise ValueError("M10 bitstream changed after build")
    owned = manifest["owned"]
    for name, size in (("m10_job", 256), ("m10_sk", SK), ("m10_wire", 972)):
        item = owned[name]
        address = item["address"]
        if item["size"] != size or address % 64 or not 0x100000 <= address <= 0x40000000 - size:
            raise ValueError("Invalid ELF-owned DDR symbol: " + name)
    return owned


def exchange(workspace, tool_root, owned, label, command, payload=b"", *, boot=False,
             expected_status=0):
    OUT.mkdir(parents=True, exist_ok=True)
    number = COMMANDS[command]
    request = JOB.pack(0x30314d45, 0, number, 0, 0, 0, 0, 0,
                       bytes(56), bytes(44), bytes(12), bytes(32), bytes(80))
    request_file, data_file = OUT / f"{label}.request", OUT / f"{label}.data"
    reply_file, log_file = OUT / f"{label}.reply", OUT / f"{label}.log"
    request_file.write_bytes(request)
    if command == "load":
        if len(payload) != SK: raise ValueError("M10 static key length")
        data_file.write_bytes(payload)
    elif command in ("begin", "finish", "rekey"):
        if len(payload) > 972: raise ValueError("M10 wire payload length")
        data_file.write_bytes(payload.ljust(972, b"\0"))
    if reply_file.exists(): reply_file.unlink()
    call = [str(tool_root / "Vivado/bin/xsdb.bat"), str(ROOT / "prj/run_m10_jtag.tcl"),
            str(workspace), str(int(boot)), command,
            str(owned["m10_job"]["address"]), str(owned["m10_sk"]["address"]),
            str(owned["m10_wire"]["address"]), str(request_file),
            str(data_file if command in ("load", "begin", "finish", "rekey") else "-"),
            str(reply_file), "120000"]
    result = subprocess.run(call, capture_output=True, text=True, timeout=300)
    log_file.write_text(result.stdout + result.stderr)
    if result.returncode or "M10_JOB_DONE" not in result.stdout:
        raise RuntimeError(f"JTAG {label} failed; see {log_file}")
    fields = JOB.unpack(reply_file.read_bytes())
    if fields[0] != 0x30314d45 or fields[1] != (3 if expected_status else 2) or (
            fields[2], fields[3]) != (number, expected_status):
        raise RuntimeError(f"Invalid M10 {label} reply: {fields[:8]}")
    return dict(state=fields[4], replay_rejected=fields[5], nonce_count=fields[6],
                zeroized=fields[7], material=fields[8], board_finished=fields[9],
                nonce=fields[10], transcript=fields[11])


def board(workspace, tool_root):
    owned = manifest_check(workspace)
    if not LIB.is_file():
        raise FileNotFoundError("Run python src/host/m09.py build first")
    pk = (M09_OUT / "public.bin").read_bytes()
    sk = (M09_OUT / "private.bin").read_bytes()
    pin = bytes.fromhex((M09_OUT / "public.sha256").read_text().strip())
    if len(pk) != PK or len(sk) != SK or sk[768:1568] != pk:
        raise ValueError("M09 static key mismatch")
    host = HostSession(pk, pin, Kem())
    loaded = False

    def handshake(label):
        hello, ack, kem = host.begin(os.urandom(32), os.urandom(32), os.urandom(32))
        response = exchange(workspace, tool_root, owned, label + "_begin", "begin",
                            hello + ack + kem)
        material = bytes(host.video_key + host.control_key) + struct.pack(
            "!II", host.epoch, host.session_id)
        if response["state"] != 2 or not hmac.compare_digest(response["material"], material) or (
                response["transcript"] != host.transcript):
            raise RuntimeError("A9/host M10 derivation mismatch")
        host.verify_board_finished(response["board_finished"])
        return material

    try:
        exchange(workspace, tool_root, owned, "load", "load", sk, boot=True)
        loaded = True
        first = handshake("first")
        old_finished = host.host_finished()
        response = exchange(workspace, tool_root, owned, "first_finish", "finish",
                            old_finished + host.command(MessageType.START))
        _, nonce = host.next_nonce()
        if response["state"] != 3 or response["nonce"] != nonce or (
                response["nonce_count"], response["replay_rejected"]) != (1, 1):
            raise RuntimeError("M10 first session nonce/replay mismatch")
        old_session_id = host.session_id
        rekey = host.command(MessageType.REKEY)
        response = exchange(workspace, tool_root, owned, "rekey", "rekey", rekey)
        if (response["state"], response["zeroized"]) != (4, 1):
            raise RuntimeError("M10 authenticated rekey did not zeroize")
        second = handshake("second")
        if second == first or host.session_id == old_session_id or host.accept_authenticated_packet(
                old_session_id, 0):
            raise RuntimeError("M10 reconnect reused key/session or accepted old packet")
        valid_start = host.command(MessageType.START)
        response = exchange(workspace, tool_root, owned, "replayed_finished", "finish",
                            old_finished + valid_start, expected_status=6)
        if response["state"] != 5 or any(response["material"] + response["nonce"]):
            raise RuntimeError("M10 old Finished was not rejected and zeroized")
        host.close("ERROR")
        third = handshake("recovery")
        response = exchange(workspace, tool_root, owned, "recovery_finish", "finish",
                            host.host_finished() + host.command(MessageType.START))
        _, nonce = host.next_nonce()
        if third in (first, second) or response["nonce"] != nonce:
            raise RuntimeError("M10 recovery reused key/nonce")
        report = dict(result="PASS", derivation_equal=True, old_finished_rejected=True,
                      old_packet_rejected=True, authenticated_rekey=True, zeroized=True,
                      reconnect_key_nonce_unique=True)
        (OUT / "board_results.json").write_text(json.dumps(report, indent=2) + "\n")
        print("M10 BOARD PASS", json.dumps(report))
    finally:
        host.close()
        if loaded:
            response = exchange(workspace, tool_root, owned, "clear", "clear")
            if (response["zeroized"], response["state"]) != (1, 4):
                raise RuntimeError("M10 board clear failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT / "build/vitis/m10_board_4")
    parser.add_argument("--tool-root", type=Path, default=Path("D:/AmdDesignTools/2026.1"))
    args = parser.parse_args()
    board(args.workspace.resolve(), args.tool_root)
