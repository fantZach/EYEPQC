"""Build/run a host-only C benchmark using the repository's ML-KEM ACVP KAT."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/keccak_host_benchmark"
KAT = ROOT / "data/kat/nist_mlkem512.json"
SOURCE = ROOT / "sim/tb/keccak_host_benchmark.c"
VENDOR_C = ROOT / "src/third_party/mlkem/mlkem_native.c"
sys.path.insert(0, str(ROOT / "sim/tb"))
from test_keccak import keccak_f1600


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_gcc():
    configured = os.environ.get("EYEPQC_HOST_CC")
    options = [configured, shutil.which("gcc"), r"C:\msys64\ucrt64\bin\gcc.exe"]
    for item in options:
        if item and Path(item).is_file():
            return Path(item).resolve()
    raise SystemExit("GCC not found; set EYEPQC_HOST_CC to the verified GCC executable")


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    gcc = find_gcc()
    exe = BUILD / ("keccak_host_benchmark.exe" if os.name == "nt" else "keccak_host_benchmark")
    flags = [
        "-std=c11", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-Werror",
        "-DMLK_CONFIG_PARAMETER_SET=512", "-DMLK_CONFIG_NAMESPACE_PREFIX=eye_mlkem",
        "-DMLK_CONFIG_NO_RANDOMIZED_API", "-DMLK_CONFIG_NO_SUPERCOP",
        "-DMLK_CONFIG_NO_KEYPAIR_API", "-DMLK_CONFIG_NO_ENCAPS_API",
        "-I", str(ROOT / "src/third_party"), "-I", str(ROOT / "src/third_party/mlkem"),
    ]
    command = [str(gcc), *flags, str(SOURCE), str(VENDOR_C), "-o", str(exe)]
    env = os.environ.copy()
    if "msys64" in str(gcc).lower():
        env["PATH"] = str(gcc.parent) + os.pathsep + str(gcc.parent.parent.parent / "usr/bin") + os.pathsep + env.get("PATH", "")
    built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=env)
    (BUILD / "build.log").write_text(built.stdout + built.stderr, encoding="utf-8")
    if built.returncode:
        raise SystemExit(f"host benchmark build failed ({built.returncode}); see {BUILD / 'build.log'}")

    vectors = json.loads(KAT.read_text(encoding="utf-8"))["decapsulation"]
    vector = vectors[0]
    (BUILD / "mlkem512_decap_input.bin").write_bytes(bytes.fromhex(vector["dk"] + vector["c"]))
    (BUILD / "mlkem512_expected_ss.bin").write_bytes(bytes.fromhex(vector["k"]))
    state = [((i + 1) * 0x0102030405060708) & ((1 << 64) - 1) for i in range(25)]
    expected_state = keccak_f1600(state)
    (BUILD / "keccak_state_input.bin").write_bytes(b"".join(x.to_bytes(8, "little") for x in state))
    (BUILD / "keccak_state_expected.bin").write_bytes(b"".join(x.to_bytes(8, "little") for x in expected_state))
    args = [str(exe), str(BUILD / "mlkem512_decap_input.bin"), str(BUILD / "mlkem512_expected_ss.bin"),
            str(BUILD / "keccak_state_input.bin"), str(BUILD / "keccak_state_expected.bin")]
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, env=env)
    (BUILD / "run.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise SystemExit(f"host benchmark failed ({result.returncode}); see {BUILD / 'run.log'}")
    marker = next((line for line in result.stdout.splitlines() if line.startswith("HOST_BENCH_OK ")), None)
    if not marker:
        raise SystemExit(f"benchmark success marker missing; see {BUILD / 'run.log'}")

    version = subprocess.run([str(gcc), "--version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    record = {
        "scope": "host process timing only; not FPGA/board performance and no acceleration ratio",
        "host": {"platform": platform.platform(), "machine": platform.machine(),
                 "processor": platform.processor(), "python": sys.version.split()[0]},
        "compiler": {"path": str(gcc), "version": version, "flags": flags,
                     "command": shlex.join(command)},
        "correctness": {"mlkem512_acvp_tcId": vector["tcId"], "decapsulation_expected_ss_match": True,
                        "keccak_state_reference": "sim/tb/test_keccak.py::keccak_f1600", "keccak_expected_state_match": True,
                        "kat_json_sha256": sha256(KAT)},
        "timing_output": marker,
        "sources": {"benchmark_c_sha256": sha256(SOURCE), "vendored_mlkem_native_c_sha256": sha256(VENDOR_C)},
        "reproduce": "python prj/keccak_host_benchmark.py",
    }
    (BUILD / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(marker)
    print(f"HOST_BENCH_REPORT={BUILD / 'result.json'}")


if __name__ == "__main__":
    main()
