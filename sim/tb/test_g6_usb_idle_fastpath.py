from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
PINNED = ROOT / "build" / "vitis" / "g6_security_cleanup_20261010_candidate009_diag4"
HARNESS = ROOT / "sim" / "tb" / "test_g6_usb_idle_fastpath.c"
NATIVE_GCC_CANDIDATES = [
    r"E:\fpg\2026.1\tps\mingw\10.0.0\win64.o\nt\bin\gcc.exe",
    r"C:\msys64\ucrt64\bin\gcc.exe",
]
INCLUDES = [
    ROOT / "src" / "ps" / "diag",
    PINNED / "usb_bounded_sdk" / "src",
    PINNED / "bsp_inputs" / "ps7_cortexa9_0" / "include",
    ROOT / "src" / "ps" / "include",
    ROOT / "src" / "third_party",
    ROOT / "prj",
    Path(r"E:\fpg\2026.1\data\embeddedsw\XilinxProcessorIPLib\drivers\usbps_v2_11\examples"),
    Path(r"E:\fpg\2026.1\data\embeddedsw\lib\bsp\standalone_v9_5\src\common\intr"),
]


class G6UsbIdleFastpathTests(unittest.TestCase):
    def test_actual_probe_and_pinned_sdk_descriptor_fastpath(self):
        compiler = (shutil.which("gcc") or shutil.which("clang") or
                    next((path for path in NATIVE_GCC_CANDIDATES
                          if Path(path).is_file()), None))
        self.assertTrue(compiler, "Native GCC or Clang is required for this offline harness")
        self.assertTrue(
            all(path.is_dir() for path in INCLUDES),
            "The immutable candidate009 pinned SDK/BSP fixture is required",
        )
        with tempfile.TemporaryDirectory(prefix="eyepqc-g6-idle-fastpath-") as temp:
            executable = Path(temp) / "g6_usb_idle_fastpath.exe"
            command = [
                compiler, "-std=c11", "-O0", "-Wall", "-Wextra",
                "-ffunction-sections", "-fdata-sections", "-Wl,--gc-sections",
                "-DG6_USB_NATIVE_TEST", "-U__arm__",
            ]
            for include in INCLUDES:
                command.extend(["-I", str(include)])
            command.extend([str(HARNESS), "-o", str(executable)])
            built = subprocess.run(command, capture_output=True, text=True, check=False)
            compile_diagnostics = "\n".join(
                (built.stderr + "\n" + built.stdout).splitlines()[-30:]
            )
            self.assertEqual(
                built.returncode, 0,
                msg=f"compile failed:\n{compile_diagnostics}\n{command}",
            )
            ran = subprocess.run([str(executable)], capture_output=True, text=True, check=False)
            self.assertEqual(ran.returncode, 0, msg=f"harness failed:\n{ran.stdout}\n{ran.stderr}")
            self.assertIn("actual_probe_idle_wipe_preserves_pipe=PASS", ran.stdout)


if __name__ == "__main__":
    unittest.main()
