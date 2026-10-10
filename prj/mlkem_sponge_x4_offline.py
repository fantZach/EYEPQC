"""Build and validate the isolated SHAKE128x4 integration offline."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src/third_party/mlkem"
EXP = ROOT / "src/ps/experimental"
OUT = ROOT / "build/mlkem_sponge_x4_offline"
CONFIG = EXP / "mlkem_sponge_backend_config.h"
REF_CONFIG = EXP / "mlkem_full_backend_ref_config.h"
KAT = ROOT / "data/kat/nist_mlkem512.json"
HOST_TEST = ROOT / "sim/tb/test_keccak_sponge_x4_host.c"
ACVP_TEST = ROOT / "sim/tb/test_mlkem_sponge_x4_acvp.c"


def compiler() -> Path:
    configured = os.environ.get("EYEPQC_HOST_CC")
    candidates = [configured, shutil.which("gcc"), r"C:\msys64\ucrt64\bin\gcc.exe"]
    for item in candidates:
        if item and Path(item).is_file():
            return Path(item).resolve()
    raise RuntimeError("GCC missing; set EYEPQC_HOST_CC to a GCC executable")


def run(cmd: list[str | Path], log: Path, env: dict[str, str]) -> str:
    p = subprocess.run([str(x) for x in cmd], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(p.stdout + p.stderr, encoding="utf-8")
    if p.returncode:
        raise RuntimeError(f"exit={p.returncode}: {' '.join(map(str, cmd))}; log={log}")
    return p.stdout + p.stderr


def compile_link(gcc: Path, env: dict[str, str], name: str,
                 sources: list[tuple[Path, Path] | tuple[Path, Path, list[str]]]) -> Path:
    common = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
              "-I", ROOT / "src/third_party", "-I", VENDOR,
              "-I", VENDOR / "src", "-I", EXP]
    objects: list[Path] = []
    for idx, item in enumerate(sources):
        src, config = item[0], item[1]
        extra = item[2] if len(item) == 3 else []
        obj = OUT / f"{name}_{idx}.o"
        run([gcc, *common, *extra, "-include", config, "-c", src, "-o", obj],
            OUT / "logs" / f"{name}_{idx}.compile.log", env)
        objects.append(obj)
    exe = OUT / (name + (".exe" if os.name == "nt" else ""))
    run([gcc, *objects, "-o", exe], OUT / "logs" / f"{name}.link.log", env)
    return exe


def decode_hex(value: str) -> bytes:
    if not isinstance(value, str) or len(value) % 2:
        raise ValueError("KAT contains malformed hex field")
    return bytes.fromhex(value)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    result_path = OUT / "result.json"
    result_path.unlink(missing_ok=True)
    gcc = compiler()
    env = os.environ.copy()
    if "msys64" in str(gcc).lower():
        env["PATH"] = str(gcc.parent) + os.pathsep + str(gcc.parent.parent.parent / "usr/bin") + os.pathsep + env.get("PATH", "")

    host_exe = compile_link(gcc, env, "sx4_host", [
        (HOST_TEST, CONFIG),
        (EXP / "keccak_sponge_x4.c", CONFIG),
        (EXP / "keccak_accel.c", CONFIG),
        (VENDOR / "src/fips202/keccakf1600.c", REF_CONFIG),
    ])
    host_log = run([host_exe], OUT / "logs/sx4_host.run.log", env)
    required = ["SX4_HOST_CONTEXT_PASS alternating_contexts=1 stale_release_preserves_owner=1 stale_replay=1",
                "SX4_HOST_CASE case=rate_minus_one_167 blocks=2 correct=1",
                "SX4_HOST_CASE case=full_rate_168 blocks=2 correct=1",
                "SX4_HOST_CASE case=rate_plus_one_169 blocks=2 correct=1",
                "SX4_HOST_CASE case=mid_timeout_3_blocks blocks=3 correct=1",
                "SX4_HOST_CASE case=mid_error_3_blocks blocks=3 correct=1",
                "SX4_HOST_CASE case=request_9_blocks blocks=9 correct=1",
                "SX4_HOST_CONTEXT_PASS cumulative_blocks_gt8=1 second_call_fallback_persistent_state=1",
                "SX4_HOST_IDENTITY_PASS mismatch_fallback=1 state_writes=0 start=0",
                "KECCAK_SX4_HOST_PASS identity_generation=1 timeout_replay=1 error_replay=1 caller_output_atomic=1 request_gt8=1 cumulative_gt8=1"]
    for marker in required:
        if marker not in host_log:
            raise RuntimeError(f"host mock marker missing: {marker}")

    acvp_exe = compile_link(gcc, env, "mlkem_sponge_x4_acvp", [
        (ACVP_TEST, CONFIG),
        (HOST_TEST, CONFIG, ["-DSX4_HOSTMOCK_LIBRARY"]),
        (VENDOR / "mlkem_native.c", CONFIG),
        (VENDOR / "src/fips202/fips202.c", CONFIG),
        (EXP / "mlkem_fips202_backend.c", CONFIG),
        (EXP / "mlkem_keccak_adapter.c", CONFIG),
        (EXP / "keccak_accel.c", CONFIG),
        (EXP / "keccak_sponge_x4.c", CONFIG),
        (VENDOR / "src/fips202/keccakf1600.c", REF_CONFIG),
    ])
    vectors = json.loads(KAT.read_text(encoding="utf-8"))
    expected_counts = {"keygen": 25, "encapsulation": 25, "decapsulation": 10}
    if {key: len(vectors.get(key, [])) for key in expected_counts} != expected_counts:
        raise RuntimeError("ML-KEM ACVP operation count mismatch")

    cases = []
    for category, records in vectors.items():
        if category not in expected_counts:
            continue
        op = {"keygen": "keygen", "encapsulation": "encaps", "decapsulation": "decaps"}[category]
        for vector in records:
            tcid = vector["tcId"]
            if op == "keygen":
                inp = decode_hex(vector["d"]) + decode_hex(vector["z"])
                expected = decode_hex(vector["ek"]) + decode_hex(vector["dk"])
            elif op == "encaps":
                inp = decode_hex(vector["ek"]) + decode_hex(vector["m"])
                expected = decode_hex(vector["c"]) + decode_hex(vector["k"])
            else:
                inp = decode_hex(vector["dk"]) + decode_hex(vector["c"])
                expected = decode_hex(vector["k"])
            case_dir = OUT / "vectors" / category / str(tcid)
            case_dir.mkdir(parents=True, exist_ok=True)
            input_path, expected_path, output_path = case_dir / "input.bin", case_dir / "expected.bin", case_dir / "actual.bin"
            input_path.write_bytes(inp)
            expected_path.write_bytes(expected)
            for path in ("hardware_mock", "timeout_fallback"):
                output_path = case_dir / f"actual_{path}.bin"
                run_output = run([acvp_exe, op, path, input_path, expected_path, output_path],
                    OUT / "logs" / f"acvp_{category}_{tcid}_{path}.log", env)
                actual = output_path.read_bytes()
                if actual != expected:
                    raise RuntimeError(f"ACVP mismatch: {category} tcId={tcid} path={path}")
                marker = re.search(r"hardware_absorbs=(\d+) hardware_squeezes=(\d+) timeout_fallbacks=(\d+)", run_output)
                if not marker:
                    raise RuntimeError(f"ACVP hardware marker missing: {category} tcId={tcid} path={path}")
                hardware_absorbs, hardware_squeezes, timeout_fallbacks = map(int, marker.groups())
                if hardware_absorbs == 0 or (path == "hardware_mock" and hardware_squeezes == 0):
                    raise RuntimeError(f"ACVP did not exercise hardware mock: {category} tcId={tcid} path={path}")
                if timeout_fallbacks != (1 if path == "timeout_fallback" else 0):
                    raise RuntimeError(f"unexpected timeout count: {category} tcId={tcid} path={path} count={timeout_fallbacks}")
                cases.append({"operation": category, "tcId": tcid, "path": path,
                              "input_sha256": hashlib.sha256(inp).hexdigest(),
                              "expected_sha256": hashlib.sha256(expected).hexdigest(),
                              "actual_sha256": hashlib.sha256(actual).hexdigest(), "match": True,
                              "hardware_absorbs": hardware_absorbs,
                              "hardware_squeeze_blocks": hardware_squeezes,
                              "timeout_fallbacks": timeout_fallbacks})
                print(f"MLKEM512_ACVP operation={category} tcId={tcid} path={path} PASS")

    provenance_files = [
        "prj/mlkem_sponge_x4_offline.py",
        "sim/tb/test_mlkem_sponge_x4_acvp.c",
        "sim/tb/test_keccak_sponge_x4_host.c",
        "sim/tb/keccak_sponge_x4_hostmock.h",
        "src/ps/experimental/keccak_sponge_x4.c",
        "src/ps/experimental/keccak_sponge_x4.h",
        "src/ps/experimental/mlkem_sponge_backend_config.h",
        "src/ps/experimental/mlkem_sponge_fips202x4_custom.h",
        "src/third_party/mlkem/mlkem_native.c",
        "src/third_party/mlkem/src/fips202/fips202.c",
        "src/third_party/mlkem/src/fips202/keccakf1600.c",
        "src/rtl/crypto/keccak_sponge_x4_axi_lite.sv",
        "sim/tb/tb_keccak_sponge_x4_axi_lite.sv",
        "data/kat/nist_mlkem512.json",
    ]
    compiler_version = run([gcc, "--version"], OUT / "logs/compiler.version.log", env).splitlines()[0]
    report = {
        "result": "MLKEM_SPONGE_X4_OFFLINE_PASS",
        "counts": expected_counts,
        "unique_vectors": sum(expected_counts.values()),
        "total_runs": len(cases),
        "host_mock_markers": [line for line in host_log.splitlines() if "PASS" in line],
        "acvp_cases": cases,
        "kat_file_sha256": hashlib.sha256(KAT.read_bytes()).hexdigest(),
        "compile_flags": ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror"],
        "compiler": {"path": str(gcc), "version": compiler_version},
        "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in provenance_files},
        "limitations": "hardware_mock is a host MMIO model using vendored C Keccak permutation, not RTL or board evidence. timeout_fallback injects a timeout on the first x4 squeeze and validates exact caller output. RTL/hashlib simulation remains separate. No board acceleration claim.",
    }
    staged_report = OUT / "result.json.tmp"
    staged_report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    staged_report.replace(result_path)
    print(f"MLKEM_SPONGE_X4_OFFLINE_PASS vectors=60 runs={len(cases)} KG=25 ENC=25 DEC=10 paths=2")
    print(f"REPORT={OUT / 'result.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"MLKEM_SPONGE_X4_OFFLINE_FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
