"""M09 offline ML-KEM-512 adapter; build the C library with `python m09.py build`."""
import argparse
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import subprocess
import struct

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "board/output/m09"
LIB = OUT / ("mlkem.dll" if os.name == "nt" else "mlkem.so")
SRC = ROOT / "src/third_party/mlkem"
PK, SK, CT, SS = 800, 1632, 768, 32


def build(path=LIB):
    path.parent.mkdir(parents=True, exist_ok=True)
    compiler = os.environ.get("CC", "gcc")
    subprocess.run([compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-DMLK_CONFIG_PARAMETER_SET=512",
                    "-DMLK_CONFIG_NAMESPACE_PREFIX=eye_mlkem",
                    "-DMLK_CONFIG_NO_RANDOMIZED_API", "-DMLK_CONFIG_NO_SUPERCOP",
                    "-I", str(SRC), "-shared", "-fPIC", str(SRC / "mlkem_native.c"),
                    "-o", str(path)], check=True)
    return path


class Kem:
    def __init__(self, path=LIB):
        self.lib = ct.CDLL(str(path))
        pointer = ct.c_void_p
        for name, count in (("keypair_derand", 3), ("enc_derand", 4),
                            ("dec", 3), ("check_pk", 1), ("check_sk", 1)):
            function = getattr(self.lib, "eye_mlkem_" + name)
            function.argtypes = [pointer] * count
            function.restype = ct.c_int

    @staticmethod
    def _input(data, length):
        if len(data) != length:
            raise ValueError(f"expected {length} bytes, got {len(data)}")
        return (ct.c_ubyte * length).from_buffer_copy(data)

    @staticmethod
    def _call(function, *args):
        status = function(*args)
        if status:
            raise ValueError(f"ML-KEM returned {status}")

    def keygen(self, coins):
        pk, sk, seed = (ct.c_ubyte * PK)(), (ct.c_ubyte * SK)(), self._input(coins, 64)
        try:
            self._call(self.lib.eye_mlkem_keypair_derand, pk, sk, seed)
            return bytes(pk), bytearray(sk)
        finally:
            ct.memset(seed, 0, 64)
            ct.memset(sk, 0, SK)

    def encaps(self, pk, coins):
        public, seed = self._input(pk, PK), self._input(coins, 32)
        ciphertext, shared = (ct.c_ubyte * CT)(), (ct.c_ubyte * SS)()
        try:
            self._call(self.lib.eye_mlkem_check_pk, public)
            self._call(self.lib.eye_mlkem_enc_derand, ciphertext, shared, public, seed)
            return bytes(ciphertext), bytearray(shared)
        finally:
            ct.memset(seed, 0, 32)
            ct.memset(shared, 0, SS)

    def decaps(self, sk, ciphertext):
        private, encrypted = self._input(sk, SK), self._input(ciphertext, CT)
        shared = (ct.c_ubyte * SS)()
        try:
            self._call(self.lib.eye_mlkem_dec, shared, encrypted, private)
            return bytearray(shared)
        finally:
            ct.memset(private, 0, SK)
            ct.memset(shared, 0, SS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("build", "keygen", "encaps", "decaps", "board"))
    parser.add_argument("--workspace", type=Path, default=ROOT / "build/vitis/m09_board_1")
    parser.add_argument("--tool-root", type=Path, default=Path("D:/AmdDesignTools/2026.1"))
    args = parser.parse_args()
    if args.operation == "build":
        print(build())
        return
    OUT.mkdir(parents=True, exist_ok=True)
    if args.operation == "board":
        board(args.workspace.resolve(), args.tool_root)
        return
    kem = Kem()
    if args.operation == "keygen":
        if (OUT / "private.bin").exists():
            raise FileExistsError("refusing to overwrite existing static board key")
        seed = bytearray(os.urandom(64))
        sk = None
        try:
            pk, sk = kem.keygen(seed)
            (OUT / "private.bin").write_bytes(sk)
            (OUT / "public.bin").write_bytes(pk)
            (OUT / "public.sha256").write_text(hashlib.sha256(pk).hexdigest() + "\n")
        finally:
            seed[:] = bytes(len(seed))
            if sk is not None:
                sk[:] = bytes(len(sk))
        print("PK_SHA256", hashlib.sha256(pk).hexdigest())
    elif args.operation == "encaps":
        pk = (OUT / "public.bin").read_bytes()
        expected = (OUT / "public.sha256").read_text().strip()
        if hashlib.sha256(pk).hexdigest() != expected:
            raise ValueError("pinned public key hash mismatch")
        coins = bytearray(os.urandom(32))
        shared = None
        try:
            ciphertext, shared = kem.encaps(pk, coins)
            (OUT / "ciphertext.bin").write_bytes(ciphertext)
            (OUT / "expected_shared.bin").write_bytes(shared)
        finally:
            coins[:] = bytes(len(coins))
            if shared is not None:
                shared[:] = bytes(len(shared))
        print("CT_SHA256", hashlib.sha256(ciphertext).hexdigest())
    else:
        private = bytearray((OUT / "private.bin").read_bytes())
        result = None
        try:
            result = kem.decaps(private, (OUT / "ciphertext.bin").read_bytes())
            print("MATCH", result == (OUT / "expected_shared.bin").read_bytes())
        finally:
            private[:] = bytes(len(private))
            if result is not None:
                result[:] = bytes(len(result))


def board(workspace, tool_root):
    manifest = json.loads((workspace / "build_manifest.json").read_text())
    for path, digest in manifest["sources"].items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest:
            raise ValueError("Board source changed: " + path)
    if hashlib.sha256(Path(manifest["elf"]).read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("Board ELF changed")
    if hashlib.sha256(Path(manifest["xsa"]).read_bytes()).hexdigest() != manifest["xsa_sha256"]:
        raise ValueError("Board XSA changed")
    owned = manifest["owned"]
    for name, size in (("m09_job", 128), ("m09_sk", SK), ("m09_ct", CT)):
        item = owned[name]
        address = item["address"]
        if item["size"] != size or address % 64 or not 0x100000 <= address <= 0x40000000 - size:
            raise ValueError("Invalid ELF-owned DDR symbol: " + name)
    pk = (OUT / "public.bin").read_bytes()
    sk = (OUT / "private.bin").read_bytes()
    ciphertext = (OUT / "ciphertext.bin").read_bytes()
    expected = (OUT / "expected_shared.bin").read_bytes()
    pin = (OUT / "public.sha256").read_text().strip()
    if (len(pk), len(sk), len(ciphertext), len(expected)) != (PK, SK, CT, SS):
        raise ValueError("Static key material has invalid length")
    if hashlib.sha256(pk).hexdigest() != pin or sk[768:1568] != pk:
        raise ValueError("Pinned public key does not match private key")

    def exchange(label, command, payload, iterations=0, boot=False):
        number = {"load": 1, "decap": 2, "clear": 3}[command]
        request = struct.pack("<8I3Q32s40s", 0x39304d45, 0, number, 0, iterations,
                              0, 0, 0, 0, 0, 0, bytes(32), bytes(40))
        request_file, data_file = OUT / f"{label}.request", OUT / f"{label}.data"
        reply_file, log_file = OUT / f"{label}.reply", OUT / f"{label}.log"
        request_file.write_bytes(request)
        if command != "clear":
            data_file.write_bytes(payload)
        if reply_file.exists():
            reply_file.unlink()
        call = [str(tool_root / "Vivado/bin/xsdb.bat"), str(ROOT / "prj/run_m09_jtag.tcl"),
                str(workspace), str(int(boot)), command,
                str(owned["m09_job"]["address"]), str(owned["m09_sk"]["address"]),
                str(owned["m09_ct"]["address"]), str(request_file),
                str(data_file if command != "clear" else "-"), str(reply_file), "120000"]
        result = subprocess.run(call, capture_output=True, text=True, timeout=300)
        log_file.write_text(result.stdout + result.stderr)
        if result.returncode or "M09_JOB_DONE" not in result.stdout:
            raise RuntimeError(f"JTAG {label} failed; see {log_file}")
        fields = struct.unpack("<8I3Q32s40s", reply_file.read_bytes())
        magic, state, reply_command, status, got_count, _, stack, heap, ticks, cycles, us, shared, _ = fields
        if (magic, state, reply_command, status, got_count) != (
                0x39304d45, 2, number, 0, iterations):
            raise RuntimeError(f"Invalid {label} reply: {fields[:5]}")
        return shared, dict(total_ticks=ticks, total_cycles=cycles, total_us=us,
                            stack_bytes=stack, heap_bytes=heap, iterations=iterations)

    acvp = json.loads((ROOT / "data/kat/nist_mlkem512.json").read_text())["encapsulation"][0]
    exchange("acvp_load", "load", bytes.fromhex(acvp["dk"]), boot=True)
    loaded = True
    try:
        shared, acvp_stats = exchange("acvp_1000", "decap", bytes.fromhex(acvp["c"]), 1000)
        if shared != bytes.fromhex(acvp["k"]):
            raise RuntimeError("A9 ACVP shared secret mismatch")
        exchange("static_load", "load", sk)
        shared, static_stats = exchange("static_1000", "decap", ciphertext, 1000)
        if shared != expected:
            raise RuntimeError("A9 static shared secret mismatch")
        tampered = bytearray(ciphertext)
        tampered[0] ^= 1
        shared, tamper_stats = exchange("tamper_1000", "decap", tampered, 1000)
        if shared == expected:
            raise RuntimeError("A9 invalid ciphertext did not reject")
        stats = dict(acvp=acvp_stats, static=static_stats, tampered=tamper_stats)
        (OUT / "board_results.json").write_text(json.dumps(stats, indent=2) + "\n")
        print("M09 BOARD PASS", json.dumps(stats))
    finally:
        if loaded:
            exchange("clear", "clear", b"")


if __name__ == "__main__":
    main()
