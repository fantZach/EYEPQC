from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "sim" / "tb" / "test_g6_cleanup_paths.c"
INCLUDES = [
    ROOT / "src" / "ps" / "include",
    ROOT / "src" / "third_party",
    ROOT / "src" / "third_party" / "tinycrypt" / "lib" / "include",
]
SOURCES = [
    HARNESS,
    ROOT / "src" / "ps" / "src" / "session.c",
    ROOT / "src" / "ps" / "src" / "protocol.c",
    ROOT / "src" / "third_party" / "tinycrypt" / "lib" / "source" / "sha256.c",
    ROOT / "src" / "third_party" / "tinycrypt" / "lib" / "source" / "utils.c",
]
NATIVE_GCC_CANDIDATES = [
    r"E:\fpg\2026.1\tps\mingw\10.0.0\win64.o\nt\bin\gcc.exe",
    r"C:\msys64\ucrt64\bin\gcc.exe",
]


def find_native_gcc() -> str | None:
    return (
        shutil.which("gcc") or shutil.which("clang") or
        next((path for path in NATIVE_GCC_CANDIDATES if Path(path).is_file()), None)
    )


class G6CleanupPathHarnessTests(unittest.TestCase):
    def test_real_g6_source_default_and_candidate_cleanup_paths(self):
        compiler = find_native_gcc()
        self.assertTrue(compiler, "Native GCC or Clang is required for this offline harness")

        with tempfile.TemporaryDirectory(prefix="eyepqc-g6-paths-") as temp:
            temp_path = Path(temp)
            stubs = temp_path / "sdk-stubs"
            stubs.mkdir()
            (stubs / "xil_printf.h").write_text(
                "#ifndef TEST_XIL_PRINTF_H\n#define TEST_XIL_PRINTF_H\n"
                "int xil_printf(const char *format, ...);\n#endif\n",
                encoding="utf-8",
            )
            (stubs / "xtime_l.h").write_text(
                "#ifndef TEST_XTIME_L_H\n#define TEST_XTIME_L_H\n"
                "#include <stdint.h>\ntypedef uint64_t XTime;\n"
                "#define COUNTS_PER_SECOND 1000000ULL\n"
                "static inline void XTime_GetTime(XTime *ticks) { *ticks = 0; }\n"
                "#endif\n",
                encoding="utf-8",
            )
            (stubs / "xil_cache.h").write_text(
                "#ifndef TEST_XIL_CACHE_H\n#define TEST_XIL_CACHE_H\n"
                "#include <stdint.h>\n"
                "void Xil_DCacheFlushRange(uintptr_t address, uint32_t length);\n"
                "#endif\n",
                encoding="utf-8",
            )

            for candidate in (False, True):
                with self.subTest(candidate_cleanup=candidate):
                    executable = temp_path / (
                        "g6_cleanup_candidate.exe" if candidate else "g6_cleanup_default.exe"
                    )
                    command = [
                        compiler, "-std=c11", "-O0", "-Wall", "-Wextra",
                        "-ffunction-sections", "-fdata-sections",
                        "-Wl,--gc-sections", "-I", str(stubs),
                    ]
                    for include in INCLUDES:
                        command.extend(["-I", str(include)])
                    if candidate:
                        command.append("-DG6_SECURE_CLEANUP")
                    command.extend(str(source) for source in SOURCES)
                    command.extend(["-o", str(executable)])
                    built = subprocess.run(
                        command, check=False, capture_output=True, text=True
                    )
                    self.assertEqual(
                        built.returncode, 0,
                        msg=f"native source harness build failed:\n{built.stderr}",
                    )
                    ran = subprocess.run(
                        [str(executable)], check=False, capture_output=True, text=True
                    )
                    self.assertEqual(
                        ran.returncode, 0,
                        msg=f"real G6 branch harness failed:\n{ran.stdout}\n{ran.stderr}",
                    )
                    expected = (
                        "candidate_cleanup_paths=PASS cleanup_failure_stops=PASS session_semantics=PASS"
                        if candidate else
                        "default_gcm_clear_paths=PASS session_semantics=PASS"
                    )
                    self.assertIn(expected, ran.stdout)


if __name__ == "__main__":
    unittest.main()
