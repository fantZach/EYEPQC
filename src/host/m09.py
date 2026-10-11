"""M09 offline ML-KEM-512 adapter; build the C library with `python m09.py build`."""
import argparse
import ctypes as ct
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import struct

from owned_ddr import require_disjoint_ranges
from transient_file import read_mutable_file, staged_file

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


def write_test_key_material(directory, public_key, private_key):
    """Persist a development test keypair, committing private.bin last.

    The presence of private.bin is the completion marker used by board tests.
    If a write fails before the final rename, no usable keypair is published.
    This is local test-key handling, not secure provisioning or storage.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if len(public_key) != PK or len(private_key) != SK:
        raise ValueError("invalid ML-KEM-512 test key lengths")
    lock_path = directory / ".m09-keygen.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        private_path = directory / "private.bin"
        if private_path.exists():
            raise FileExistsError("refusing to overwrite existing static board key")
        public_path = directory / "public.bin"
        pin_path = directory / "public.sha256"
        pin_data = (hashlib.sha256(public_key).hexdigest() + "\n").encode("ascii")
        with staged_file(directory, ".m09-public-", public_key) as staged_public:
            os.replace(staged_public, public_path)
        with staged_file(directory, ".m09-pin-", pin_data) as staged_pin:
            os.replace(staged_pin, pin_path)
        # Publish the private key last. Readers treat it as the keyset commit marker.
        with staged_file(directory, ".m09-private-", private_key) as staged_private:
            os.replace(staged_private, private_path)
    finally:
        os.close(lock_fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def load_test_public_key(directory):
    """Load the public key only when the private-last keyset commit marker exists."""
    directory = Path(directory)
    if not (directory / "private.bin").is_file():
        raise FileNotFoundError("M09 test keyset is incomplete; run keygen")
    public_key = (directory / "public.bin").read_bytes()
    expected_pin = (directory / "public.sha256").read_text().strip()
    if len(public_key) != PK or hashlib.sha256(public_key).hexdigest() != expected_pin:
        raise ValueError("pinned public key hash mismatch")
    return public_key


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
            write_test_key_material(OUT, pk, sk)
        finally:
            seed[:] = bytes(len(seed))
            if sk is not None:
                sk[:] = bytes(len(sk))
        print("PK_SHA256", hashlib.sha256(pk).hexdigest())
    elif args.operation == "encaps":
        pk = load_test_public_key(OUT)
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
        private = read_mutable_file(OUT / "private.bin", SK)
        result = None
        expected = None
        try:
            result = kem.decaps(private, (OUT / "ciphertext.bin").read_bytes())
            expected = read_mutable_file(OUT / "expected_shared.bin", SS)
            print("MATCH", result == expected)
        finally:
            private[:] = bytes(len(private))
            if expected is not None:
                expected[:] = bytes(len(expected))
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
    require_disjoint_ranges(((name, owned[name]["address"], owned[name]["size"])
                             for name in ("m09_job", "m09_sk", "m09_ct")),
                            "ELF-owned M09 buffers")
    pk = (OUT / "public.bin").read_bytes()
    sk = read_mutable_file(OUT / "private.bin", SK)
    expected = None
    loaded = False

    def exchange(label, command, payload, iterations=0, boot=False):
        number = {"load": 1, "decap": 2, "clear": 3}[command]
        request = struct.pack("<8I3Q32s40s", 0x39304d45, 0, number, 0, iterations,
                              0, 0, 0, 0, 0, 0, bytes(32), bytes(40))
        log_file = OUT / f"{label}.log"
        with staged_file(OUT, f".{label}-request-", request) as request_file, \
                staged_file(OUT, f".{label}-data-", payload if command != "clear" else None) as data_file, \
                staged_file(OUT, f".{label}-reply-") as reply_file:
            call = [str(tool_root / "Vivado/bin/xsdb.bat"), str(ROOT / "prj/run_m09_jtag.tcl"),
                    str(workspace), str(int(boot)), command,
                    str(owned["m09_job"]["address"]), str(owned["m09_sk"]["address"]),
                    str(owned["m09_ct"]["address"]), str(request_file),
                    str(data_file if command != "clear" else "-"), str(reply_file), "120000"]
            result = subprocess.run(call, capture_output=True, text=True, timeout=300)
            log_file.write_text(result.stdout + result.stderr)
            if result.returncode or "M09_JOB_DONE" not in result.stdout:
                raise RuntimeError(f"JTAG {label} failed; see {log_file}")
            reply = read_mutable_file(reply_file, 128)
            try:
                fields = struct.unpack_from("<8I3Q", reply)
                if (fields[0], fields[1], fields[2], fields[3], fields[4]) != (
                        0x39304d45, 2, number, 0, iterations):
                    raise RuntimeError(f"Invalid {label} reply: {fields[:5]}")
                shared = bytearray(memoryview(reply)[56:88])
                return shared, dict(total_ticks=fields[8], total_cycles=fields[9],
                                    total_us=fields[10], stack_bytes=fields[6],
                                    heap_bytes=fields[7], iterations=iterations)
            finally:
                reply[:] = bytes(len(reply))

    try:
        ciphertext = (OUT / "ciphertext.bin").read_bytes()
        expected = read_mutable_file(OUT / "expected_shared.bin", SS)
        pin = (OUT / "public.sha256").read_text().strip()
        if (len(pk), len(sk), len(ciphertext), len(expected)) != (PK, SK, CT, SS):
            raise ValueError("Static key material has invalid length")
        if hashlib.sha256(pk).hexdigest() != pin or sk[768:1568] != pk:
            raise ValueError("Pinned public key does not match private key")

        acvp = json.loads((ROOT / "data/kat/nist_mlkem512.json").read_text())["encapsulation"][0]
        loaded = True  # Clear the AP0 key region even if the initial load times out.
        exchange("acvp_load", "load", bytes.fromhex(acvp["dk"]), boot=True)

        def decaps_and_check(label, payload, reference):
            result = None
            try:
                result, stats = exchange(label, "decap", payload, 1000)
                if not hmac.compare_digest(result, reference):
                    raise RuntimeError(f"A9 {label} shared secret mismatch")
                return stats
            finally:
                if result is not None:
                    result[:] = bytes(len(result))

        acvp_stats = decaps_and_check("acvp_1000", bytes.fromhex(acvp["c"]),
                                      bytes.fromhex(acvp["k"]))
        exchange("static_load", "load", sk)
        static_stats = decaps_and_check("static_1000", ciphertext, expected)
        tampered = bytearray(ciphertext)
        tampered[0] ^= 1
        tamper_result = None
        try:
            tamper_result, tamper_stats = exchange("tamper_1000", "decap", tampered, 1000)
            if hmac.compare_digest(tamper_result, expected):
                raise RuntimeError("A9 invalid ciphertext did not reject")
        finally:
            tampered[:] = bytes(len(tampered))
            if tamper_result is not None:
                tamper_result[:] = bytes(len(tamper_result))
        stats = dict(acvp=acvp_stats, static=static_stats, tampered=tamper_stats)
        (OUT / "board_results.json").write_text(json.dumps(stats, indent=2) + "\n")
        print("M09 BOARD PASS", json.dumps(stats))
    finally:
        try:
            if loaded:
                exchange("clear", "clear", b"")
        finally:
            sk[:] = bytes(len(sk))
            if expected is not None:
                expected[:] = bytes(len(expected))


if __name__ == "__main__":
    main()
