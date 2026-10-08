"""Build/run actual ML-KEM-512 Decaps through the experimental Keccak adapter."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/mlkem_full_backend_mock"
VENDOR = ROOT / "src/third_party/mlkem"
EXPERIMENT = ROOT / "src/ps/experimental"
KAT = ROOT / "data/kat/nist_mlkem512.json"
SOURCES = {
    "harness": ROOT / "sim/tb/test_mlkem_full_backend.c",
    "mlkem_scu": VENDOR / "mlkem_native.c",
    "fips202": VENDOR / "src/fips202/fips202.c",
    "reference_keccak": VENDOR / "src/fips202/keccakf1600.c",
    "accel_driver": EXPERIMENT / "keccak_accel.c",
    "adapter": EXPERIMENT / "mlkem_keccak_adapter.c",
    "dispatch": EXPERIMENT / "mlkem_fips202_backend.c",
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gcc_path():
    configured = os.environ.get("EYEPQC_HOST_CC")
    candidates = [configured, shutil.which("gcc"), r"C:\msys64\ucrt64\bin\gcc.exe"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise SystemExit("GCC not found; set EYEPQC_HOST_CC to the verified GCC executable")


def run(command, env, log):
    result = subprocess.run([str(x) for x in command], cwd=ROOT, env=env,
                            capture_output=True, text=True)
    Path(log).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}); see {log}")
    return result.stdout + result.stderr


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    gcc = gcc_path()
    env = os.environ.copy()
    if "msys64" in str(gcc).lower():
        env["PATH"] = str(gcc.parent) + os.pathsep + str(gcc.parent.parent.parent / "usr/bin") + os.pathsep + env.get("PATH", "")
    common = ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
              "-I", str(ROOT / "src/third_party"), "-I", str(VENDOR),
              "-I", str(VENDOR / "src"), "-I", str(EXPERIMENT)]
    objects = []
    for key, source in SOURCES.items():
        config = EXPERIMENT / ("mlkem_full_backend_ref_config.h" if key == "reference_keccak"
                               else "mlkem_full_backend_config.h")
        obj = BUILD / f"{key}.o"
        command = [gcc, *common, "-include", config, "-c", source, "-o", obj]
        run(command, env, BUILD / f"{key}.compile.log")
        objects.append(obj)
    exe = BUILD / ("mlkem_full_backend.exe" if os.name == "nt" else "mlkem_full_backend")
    link_cmd = [gcc, *objects, "-o", exe]
    run(link_cmd, env, BUILD / "link.log")

    vector = json.loads(KAT.read_text(encoding="utf-8"))["decapsulation"][0]
    tc_input = bytes.fromhex(vector["dk"] + vector["c"])
    expected = bytes.fromhex(vector["k"])
    input_file = BUILD / "mlkem512_tc76_sk_ct.bin"
    expected_file = BUILD / "mlkem512_tc76_ss.bin"
    input_file.write_bytes(tc_input)
    expected_file.write_bytes(expected)
    output = run([exe, input_file, expected_file], env, BUILD / "run.log")
    marker = "MLKEM_FULL_BACKEND_PASS vendor_unchanged=1 real_decapsulation=1 kat_tcId=76 mock_only=1"
    if marker not in output:
        raise RuntimeError(f"expected pass marker missing; see {BUILD / 'run.log'}")
    record = {
        "result": marker,
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "compiler": {"path": str(gcc), "version": run([gcc, "--version"], env, BUILD / "gcc_version.log").splitlines()[0],
                     "flags": common + ["-include <experiment-config>", "-c", "<source>"],
                     "link_command": [str(x) for x in link_cmd]},
        "configuration": {"parameter_set": 512, "serial_fips202_only": True,
                          "custom_header": "mlkem_fips202_custom.h", "vendored_sources_modified": False},
        "kat": {"tcId": vector["tcId"], "ct_sha256": hashlib.sha256(bytes.fromhex(vector["c"])).hexdigest(),
                "dk_sha256": hashlib.sha256(bytes.fromhex(vector["dk"])).hexdigest(),
                "expected_ss_sha256": hashlib.sha256(expected).hexdigest(), "match": True},
        "cases": output.splitlines(),
        "sources_sha256": {key: sha256(path) for key, path in SOURCES.items()},
        "vendor_source_sha256": {"mlkem_native.c": sha256(VENDOR / "mlkem_native.c"),
                                 "fips202.c": sha256(VENDOR / "src/fips202/fips202.c"),
                                 "keccakf1600.c": sha256(VENDOR / "src/fips202/keccakf1600.c")},
        "limits": "software MMIO mock uses vendored C Keccak to model permutation result; no RTL simulation, board, or acceleration claim",
    }
    (BUILD / "result.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(output.strip())
    print(f"MLKEM_FULL_BACKEND_REPORT={BUILD / 'result.json'}")


if __name__ == "__main__":
    main()
