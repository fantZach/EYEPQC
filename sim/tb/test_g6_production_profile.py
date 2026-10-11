from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "sim" / "tb" / "test_g6_production_profile.c"
INCLUDES = [
    ROOT / "src" / "ps" / "include",
    ROOT / "src" / "third_party",
    ROOT / "src" / "third_party" / "tinycrypt" / "lib" / "include",
]
SOURCES = [
    HARNESS,
    ROOT / "src" / "ps" / "src" / "session.c",
    ROOT / "src" / "ps" / "src" / "g6_hmac_drbg.c",
    ROOT / "src" / "ps" / "src" / "protocol.c",
    ROOT / "src" / "third_party" / "tinycrypt" / "lib" / "source" / "sha256.c",
    ROOT / "src" / "third_party" / "tinycrypt" / "lib" / "source" / "utils.c",
]
GCC_CANDIDATES = [
    os.environ.get("CC", ""),
    shutil.which("gcc") or "",
    shutil.which("clang") or "",
    r"D:\Program Files\clion\CLion 2025.2.2\bin\mingw\bin\gcc.exe",
    r"C:\msys64\ucrt64\bin\gcc.exe",
]


def find_compiler() -> str | None:
    return next((candidate for candidate in GCC_CANDIDATES
                 if candidate and Path(candidate).is_file()), None)


class G6ProductionProfileTests(unittest.TestCase):
    def test_real_g6_production_provider_profile(self):
        compiler = find_compiler()
        self.assertTrue(compiler, "A native GCC or Clang compiler is required")
        with tempfile.TemporaryDirectory(prefix="eyepqc-g6-production-") as temp:
            temp_path = Path(temp)
            stubs = temp_path / "sdk-stubs"
            stubs.mkdir()
            (stubs / "xil_printf.h").write_text(
                "int xil_printf(const char *format, ...);\n", encoding="ascii")
            (stubs / "xtime_l.h").write_text(
                "#include <stdint.h>\ntypedef uint64_t XTime;\n"
                "#define COUNTS_PER_SECOND 1000000ULL\n"
                "static inline void XTime_GetTime(XTime *ticks) { *ticks = 0; }\n",
                encoding="ascii")
            executable = temp_path / "g6_production_profile.exe"
            command = [compiler, "-std=c11", "-O0", "-Wall", "-Wextra",
                       "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                       "-DG6_PRODUCTION", "-I", str(stubs)]
            for include in INCLUDES:
                command.extend(["-I", str(include)])
            command.extend(str(source) for source in SOURCES)
            command.extend(["-o", str(executable)])
            built = subprocess.run(command, check=False, capture_output=True, text=True)
            self.assertEqual(built.returncode, 0,
                             msg=f"production-profile harness build failed:\n{built.stderr}")
            ran = subprocess.run([str(executable)], check=False,
                                 capture_output=True, text=True)
            self.assertEqual(ran.returncode, 0,
                             msg=f"production-profile harness failed:\n{ran.stdout}\n{ran.stderr}")
            self.assertIn("G6_PRODUCTION_PROFILE_PASS", ran.stdout)

            nm = Path(compiler).with_name("nm.exe")
            if not nm.is_file():
                nm_on_path = shutil.which("nm")
                nm = Path(nm_on_path) if nm_on_path else nm
            self.assertTrue(nm.is_file(), "Compiler's nm tool is required for mailbox-symbol check")
            symbols = subprocess.run([str(nm), str(executable)], check=True,
                                     capture_output=True, text=True).stdout
            for development_symbol in ("g6_sk_load", "g6_seed_load", "g6_ready", "random_seed"):
                self.assertNotIn(development_symbol, symbols)


if __name__ == "__main__":
    unittest.main()
