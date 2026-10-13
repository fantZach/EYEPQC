"""The shared DDR linker must not emit a zero-address build-id LOAD segment."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class DDRLinker(unittest.TestCase):
    def test_build_id_cannot_create_ocm_partition(self):
        tools = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
        gcc = shutil.which("arm-none-eabi-gcc") or str(
            tools / "Vitis/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe")
        if not Path(gcc).is_file():
            self.skipTest("ARM GCC not installed")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "probe.c"
            elf = Path(directory) / "probe.elf"
            source.write_text('void _vector_table(void) { for (;;) {} }\n'
                              'volatile unsigned char scratch[65536];\n', encoding="ascii")
            subprocess.run([gcc, "-mcpu=cortex-a9", "-nostdlib", "-Wl,--build-id",
                            "-T", str(ROOT / "board/prj/a9_ddr.ld"), str(source),
                            "-o", str(elf)], check=True, capture_output=True)
            image = elf.read_bytes()
            self.assertEqual(image[:6], b"\x7fELF\x01\x01")
            entry, offset = struct.unpack_from("<II", image, 24)
            size, count = struct.unpack_from("<HH", image, 42)
            loads = [struct.unpack_from("<8I", image, offset + index * size)
                     for index in range(count)]
            loads = [header for header in loads if header[0] == 1]
            self.assertTrue(loads)
            for _, _, virtual, physical, _, memory, _, _ in loads:
                self.assertEqual(virtual, physical)
                self.assertGreaterEqual(physical, 0x00100000)
                self.assertLessEqual(physical + memory, 0x40000000)
            self.assertTrue(any(header[3] <= entry < header[3] + header[5]
                                and header[6] & 1 for header in loads))


if __name__ == "__main__":
    unittest.main()
