from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sim" / "tb" / "test_g6_secure_cleanup_harness.c"
INCLUDE = ROOT / "src" / "ps" / "include"


def test_g6_secure_cleanup_real_header_harness():
    gcc = (shutil.which("gcc") or shutil.which("clang") or
           (r"E:\fpg\2026.1\tps\mingw\10.0.0\win64.o\nt\bin\gcc.exe"
            if Path(r"E:\fpg\2026.1\tps\mingw\10.0.0\win64.o\nt\bin\gcc.exe").is_file()
            else None) or
           (r"C:\msys64\ucrt64\bin\gcc.exe"
            if Path(r"C:\msys64\ucrt64\bin\gcc.exe").is_file()
            else None))
    assert gcc, "Native GCC or Clang is required for the secure cleanup harness"
    with tempfile.TemporaryDirectory(prefix="eyepqc-g6-secure-cleanup-") as temp:
        executable = Path(temp) / "g6_secure_cleanup_test.exe"
        subprocess.run(
            [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-I", str(INCLUDE), str(SOURCE), "-o", str(executable)],
            check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            [str(executable)], check=True, capture_output=True, text=True,
        )
        assert "full_capacity_wipe=PASS" in result.stdout
        assert "gates_and_order=PASS" in result.stdout
        assert "tx_sequence=PASS" in result.stdout
        assert "disconnect_classification=PASS" in result.stdout
