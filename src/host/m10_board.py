"""Run the M10 offline handshake against the A9 over JTAG (no Ethernet)."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import struct
import subprocess

from handshake import HostSession, wipe_secret
from m09 import Kem, LIB, OUT as M09_OUT, PK, SK
from protocol import MessageType
from transient_file import read_mutable_file, staged_file

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
    log_file = OUT / f"{label}.log"
    if command == "load":
        if len(payload) != SK:
            raise ValueError("M10 static key length")
        transfer_data = payload
    elif command in ("begin", "finish", "rekey"):
        if len(payload) > 972:
            raise ValueError("M10 wire payload length")
        transfer_data = payload.ljust(972, b"\0")
    else:
        transfer_data = None

    with staged_file(OUT, f".{label}-request-", request) as request_file, \
            staged_file(OUT, f".{label}-data-", transfer_data) as data_file, \
            staged_file(OUT, f".{label}-reply-") as reply_file:
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
        reply = read_mutable_file(reply_file, JOB.size)
        try:
            header = struct.unpack_from("<8I", reply)
            if header[0] != 0x30314d45 or header[1] != (3 if expected_status else 2) or (
                    header[2], header[3]) != (number, expected_status):
                raise RuntimeError(f"Invalid M10 {label} reply: {header}")
            view = memoryview(reply)
            return dict(state=header[4], replay_rejected=header[5], nonce_count=header[6],
                        zeroized=header[7], material=bytearray(view[32:88]),
                        board_finished=bytearray(view[88:132]), nonce=bytearray(view[132:144]),
                        transcript=bytearray(view[144:176]))
        finally:
            wipe_secret(reply)


def board(workspace, tool_root):
    owned = manifest_check(workspace)
    if not LIB.is_file():
        raise FileNotFoundError("Run python src/host/m09.py build first")
    pk = (M09_OUT / "public.bin").read_bytes()
    sk = read_mutable_file(M09_OUT / "private.bin", SK)
    pin = None
    host = None
    loaded = False
    derived_materials = []
    old_finished = None

    def wipe_response(response):
        if response is not None:
            for field in ("material", "board_finished", "nonce", "transcript"):
                wipe_secret(response.get(field))

    def handshake(label):
        coins = bytearray(os.urandom(32))
        try:
            hello, ack, kem = host.begin(os.urandom(32), os.urandom(32), coins)
        finally:
            wipe_secret(coins)
        response = exchange(workspace, tool_root, owned, label + "_begin", "begin",
                            hello + ack + kem)
        material = bytearray(56)
        material[:16] = host.video_key
        material[16:48] = host.control_key
        struct.pack_into("!II", material, 48, host.epoch, host.session_id)
        try:
            if response["state"] != 2 or not hmac.compare_digest(response["material"], material) or (
                    response["transcript"] != host.transcript):
                raise RuntimeError("A9/host M10 derivation mismatch")
            host.verify_board_finished(response["board_finished"])
            return material
        except BaseException:
            wipe_secret(material)
            raise
        finally:
            wipe_response(response)

    try:
        pin = bytes.fromhex((M09_OUT / "public.sha256").read_text().strip())
        if len(pk) != PK or len(sk) != SK or sk[768:1568] != pk:
            raise ValueError("M09 static key mismatch")
        host = HostSession(pk, pin, Kem())
        loaded = True  # Clear the AP0 key region even if the initial load times out.
        exchange(workspace, tool_root, owned, "load", "load", sk, boot=True)
        first = handshake("first")
        derived_materials.append(first)
        old_finished = bytearray(host.host_finished())
        finish_payload = bytearray(old_finished)
        finish_payload.extend(host.command(MessageType.START))
        try:
            response = exchange(workspace, tool_root, owned, "first_finish", "finish",
                                finish_payload)
        finally:
            wipe_secret(finish_payload)
        try:
            _, nonce = host.next_nonce()
            if response["state"] != 3 or response["nonce"] != nonce or (
                    response["nonce_count"], response["replay_rejected"]) != (1, 1):
                raise RuntimeError("M10 first session nonce/replay mismatch")
        finally:
            wipe_response(response)
        old_session_id = host.session_id
        rekey = bytearray(host.command(MessageType.REKEY))
        try:
            response = exchange(workspace, tool_root, owned, "rekey", "rekey", rekey)
        finally:
            wipe_secret(rekey)
        try:
            if (response["state"], response["zeroized"]) != (4, 1):
                raise RuntimeError("M10 authenticated rekey did not zeroize")
        finally:
            wipe_response(response)
        second = handshake("second")
        derived_materials.append(second)
        if hmac.compare_digest(second, first) or host.session_id == old_session_id or host.accept_authenticated_packet(
                old_session_id, 0):
            raise RuntimeError("M10 reconnect reused key/session or accepted old packet")
        valid_start = bytearray(host.command(MessageType.START))
        finish_payload = bytearray(old_finished)
        finish_payload.extend(valid_start)
        try:
            response = exchange(workspace, tool_root, owned, "replayed_finished", "finish",
                                finish_payload, expected_status=6)
        finally:
            wipe_secret(finish_payload)
            wipe_secret(valid_start)
        try:
            if response["state"] != 5 or any(response["material"] + response["nonce"]):
                raise RuntimeError("M10 old Finished was not rejected and zeroized")
        finally:
            wipe_response(response)
        host.close("ERROR")
        third = handshake("recovery")
        derived_materials.append(third)
        finish_payload = bytearray(host.host_finished())
        finish_payload.extend(host.command(MessageType.START))
        try:
            response = exchange(workspace, tool_root, owned, "recovery_finish", "finish",
                                finish_payload)
        finally:
            wipe_secret(finish_payload)
        try:
            _, nonce = host.next_nonce()
            if hmac.compare_digest(third, first) or hmac.compare_digest(third, second) or response["nonce"] != nonce:
                raise RuntimeError("M10 recovery reused key/nonce")
        finally:
            wipe_response(response)
        report = dict(result="PASS", derivation_equal=True, old_finished_rejected=True,
                      old_packet_rejected=True, authenticated_rekey=True, zeroized=True,
                      reconnect_key_nonce_unique=True)
        (OUT / "board_results.json").write_text(json.dumps(report, indent=2) + "\n")
        print("M10 BOARD PASS", json.dumps(report))
    finally:
        try:
            if loaded:
                response = exchange(workspace, tool_root, owned, "clear", "clear")
                try:
                    if (response["zeroized"], response["state"]) != (1, 4):
                        raise RuntimeError("M10 board clear failed")
                finally:
                    wipe_response(response)
        finally:
            if host is not None:
                host.close()
            for material in derived_materials:
                wipe_secret(material)
            wipe_secret(old_finished)
            wipe_secret(sk)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=ROOT / "build/vitis/m10_board_4")
    parser.add_argument("--tool-root", type=Path, default=Path("D:/AmdDesignTools/2026.1"))
    args = parser.parse_args()
    board(args.workspace.resolve(), args.tool_root)
