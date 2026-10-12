from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "sim" / "tb" / "test_g6_control_dispatch.c"
INCLUDE = ROOT / "board" / "src" / "ps" / "include"


def test_g6_control_dispatch_real_header_harness():
    gcc = (shutil.which("gcc") or shutil.which("clang") or
           (r"E:\fpg\2026.1\tps\mingw\10.0.0\win64.o\nt\bin\gcc.exe"
            if Path(r"E:\fpg\2026.1\tps\mingw\10.0.0\win64.o\nt\bin\gcc.exe").is_file()
            else None) or
           (r"C:\msys64\ucrt64\bin\gcc.exe"
            if Path(r"C:\msys64\ucrt64\bin\gcc.exe").is_file()
            else None))
    assert gcc, "Native GCC or Clang is required for the G6 control dispatch harness"
    with tempfile.TemporaryDirectory(prefix="eyepqc-g6-control-") as temp:
        executable = Path(temp) / "g6_control_dispatch_test.exe"
        subprocess.run(
            [gcc, "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-I", str(INCLUDE), str(SOURCE), "-o", str(executable)],
            check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            [str(executable)], check=True, capture_output=True, text=True,
        )
        assert "normal=PASS" in result.stdout
        assert "handler_failure=PASS" in result.stdout
        assert "take_partial_failure=PASS" in result.stdout
        assert "idle=PASS" in result.stdout
        assert "oversized=PASS" in result.stdout
