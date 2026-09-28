"""Run one bounded native DMA job; never run concurrent XSDB sessions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
from datetime import datetime

ROOT = Path(__file__).resolve().parents[2]
FIELDS = "magic state command count cache status completed bytes checksum elapsed_us rx_irq tx_irq error_irq timeouts resets held_rejects address length frames queued dropped overflows peak sent camera_status pclk_hz max_length cap_status tx_status crypto_status stalls reserved".split()

def reply(data):
    if len(data) != 128: raise ValueError("Invalid mailbox size")
    result = dict(zip(FIELDS, struct.unpack("<32I", data)))
    if result["magic"] != 0x35414d44 or result["state"] not in (2, 3):
        raise ValueError("Invalid completed mailbox")
    return result

def jpeg(data, result, owned):
    n = result["length"]
    base = owned["dma_frames"]["address"]
    if result["address"] not in (base, base + 65600) or not 4 <= n <= 65536:
        raise ValueError("Frame outside ELF-owned buffers")
    if len(data) != (n + 3) // 4 * 4: raise ValueError("Truncated DDR read")
    data = data[:n]
    if data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9": raise ValueError("Invalid JPEG boundaries")
    checksum = 2166136261
    for byte in data: checksum = ((checksum ^ byte) * 16777619) & 0xffffffff
    if checksum != result["checksum"]: raise ValueError("DDR frame checksum mismatch")
    return data

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("workspace", type=Path)
    p.add_argument("command", choices=("test", "camera", "release"))
    p.add_argument("--boot", action="store_true", help="Download volatile bit/ELF before this job")
    p.add_argument("--count", type=int, default=32)
    p.add_argument("--cache", type=int, choices=(0, 1), default=1)
    p.add_argument("--size", choices=("320x240", "640x480"), default="320x240")
    p.add_argument("--quality", type=int, default=12, help="OV5640 quantization parameter 0..63")
    p.add_argument("--vts", type=int, default=1968, help="Sensor timing calibration 1000..5000")
    p.add_argument("--tool-root", type=Path, default=Path("D:/AmdDesignTools/2026.1"))
    args = p.parse_args()
    if not 1 <= args.count <= 10000: p.error("count must be 1..10000")
    if not 0 <= args.quality <= 63 or not 1000 <= args.vts <= 5000: p.error("Invalid sensor quality/VTS")
    workspace = args.workspace.resolve()
    manifest = json.loads((workspace / "build_manifest.json").read_text())
    for path, digest in manifest["artifacts"].items():
        if hashlib.sha256((workspace / path).read_bytes()).hexdigest() != digest:
            raise ValueError("Build artifact changed: " + path)
    if hashlib.sha256(Path(manifest["xsa"]).read_bytes()).hexdigest() != manifest["xsa_sha256"]:
        raise ValueError("XSA changed")
    owned = manifest["owned"]
    for name, size in {"dma_job": 128, "dma_frames": 131200, "dma_packet": 65600}.items():
        a = owned[name]["address"]
        if owned[name]["size"] != size or a % 64 or not 0x100000 <= a < 0x40000000 - size:
            raise ValueError("Invalid owned ABI")
    target = ROOT / "data/captures" / ("m05_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    target.mkdir(parents=True)
    cmd = {"test": 1, "camera": 2, "release": 3}[args.command]
    timeout_ms = args.count * 3100 + 10000 if cmd == 2 else 180000
    sensor_cfg = args.vts << 9 | args.quality << 3 | (4 if args.size == "640x480" else 0) | 2
    call = [str(args.tool_root / "Vivado/bin/xsdb.bat"), str(ROOT / "prj/run_m05_jtag.tcl"),
        str(workspace), str(int(args.boot)), str(cmd), str(args.count), str(args.cache),
        str(owned["dma_job"]["address"]), str(owned["dma_frames"]["address"]),
        str(target / "reply.bin"), str(target / "frame.ddr"), str(timeout_ms), str(sensor_cfg)]
    with subprocess.Popen(call, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout_ms / 1000 + 180)
        except subprocess.TimeoutExpired:
            # .bat launches children: killing just cmd.exe can leave XSDB accessing the board.
            if os.name == "nt": subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False)
            else: process.kill()
            stdout, stderr = process.communicate(timeout=30)
            (target / "xsdb.log").write_text(stdout + stderr + "\nHOST XSDB TIMEOUT\n", encoding="utf-8")
            raise RuntimeError(f"XSDB process tree stopped after timeout; see {target}")
    (target / "xsdb.log").write_text(stdout + stderr, encoding="utf-8")
    print(stdout, end="")
    print(stderr, end="")
    if process.returncode or "M05_JOB_DONE" not in stdout: raise RuntimeError(f"XSDB failed; see {target}")
    result = reply((target / "reply.bin").read_bytes())
    result.update(workspace=str(workspace), bit_sha256=manifest["artifacts"]["camera_dma/_ide/bitstream/m01.bit"],
                  boot=args.boot)
    if result["command"] != cmd or result["count"] != args.count or result["cache"] != args.cache:
        raise RuntimeError("Reply does not match command")
    if result["state"] == 2 and result["status"] == 0 and cmd == 2:
        image = jpeg((target / "frame.ddr").read_bytes(), result, owned)
        (target / "frame.jpg").write_bytes(image)
        result["jpeg_sha256"] = hashlib.sha256(image).hexdigest()
    (target / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if result["status"] or result["state"] != 2: raise RuntimeError(f"Board failure; see {target}")
    if cmd != 3 and not 0 < result["elapsed_us"] <= timeout_ms * 1000:
        raise RuntimeError("Invalid timer/deadline measurement")
    if cmd == 1 and (result["completed"] != args.count + 2 or not result["error_irq"] or
                     result["timeouts"] != 1 or not result["rx_irq"] or not result["tx_irq"] or
                     result["held_rejects"] < (args.count + 1) // 2 - 1 or
                     (args.count >= 24 and (not result["stalls"] or result["max_length"] != 65536))):
        raise RuntimeError("Incomplete pattern/recovery test")
    if cmd == 2 and result["frames"] != args.count: raise RuntimeError("Incomplete camera test")
    print("M05_HOST_OK", target)

if __name__ == "__main__": main()
