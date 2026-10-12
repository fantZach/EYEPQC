from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCES = [
    ROOT / "sim" / "tb" / "test_g6_hmac_drbg.c",
    ROOT / "board" / "src" / "ps" / "src" / "g6_hmac_drbg.c",
    ROOT / "board" / "src" / "ps" / "src" / "session.c",
    ROOT / "board" / "src" / "ps" / "src" / "protocol.c",
    ROOT / "board" / "src" / "third_party" / "tinycrypt" / "lib" / "source" / "sha256.c",
    ROOT / "board" / "src" / "third_party" / "tinycrypt" / "lib" / "source" / "utils.c",
]
INCLUDES = [
    ROOT / "board" / "src" / "ps" / "include",
    ROOT / "board" / "src" / "third_party" / "tinycrypt" / "lib" / "include",
]
COMPILERS = [os.environ.get("CC", ""), shutil.which("gcc") or "",
             shutil.which("clang") or "",
             r"D:\Program Files\clion\CLion 2025.2.2\bin\mingw\bin\gcc.exe",
             r"C:\msys64\ucrt64\bin\gcc.exe"]


def find_compiler() -> str | None:
    return next((compiler for compiler in COMPILERS
                 if compiler and Path(compiler).is_file()), None)


class G6HmacDrbgTests(unittest.TestCase):
    def test_nist_vectors_and_fail_closed_contract(self):
        compiler = find_compiler()
        self.assertTrue(compiler, "A native GCC or Clang compiler is required")
        with tempfile.TemporaryDirectory(prefix="eyepqc-hmac-drbg-") as temp:
            executable = Path(temp) / "test_g6_hmac_drbg.exe"
            command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror"]
            for include in INCLUDES:
                command += ["-I", str(include)]
            command += [str(source) for source in SOURCES] + ["-o", str(executable)]
            built = subprocess.run(command, capture_output=True, text=True, check=False)
            self.assertEqual(built.returncode, 0, msg=built.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True,
                                    check=False)
            self.assertEqual(result.returncode, 0,
                             msg=f"{result.stdout}\n{result.stderr}")
            self.assertIn("G6_HMAC_DRBG_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
