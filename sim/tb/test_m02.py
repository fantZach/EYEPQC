"""Pin-level SCCB and OV5640 configuration checks; no connected board required."""
import os
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def tool(name):
    found = shutil.which(name)
    if found:
        return found
    windows = Path(f"C:/iverilog/bin/{name}.exe")
    if os.name == "nt" and windows.is_file():
        return str(windows)
    raise RuntimeError(f"Install {name} or add it to PATH")


class M02(unittest.TestCase):
    def test_register_facts(self):
        self.assertIn("set_property synth_checkpoint_mode None [get_files system.bd]",
                      (ROOT / "prj/build_m01.tcl").read_text())
        words = [line.strip() for line in (ROOT / "src/rtl/camera/ov5640_jpeg.mem").read_text().splitlines()
                 if line.strip() and not line.startswith("//")]
        self.assertEqual(len(words), 251)
        self.assertEqual(words[:3], ["300882", "300802", "310302"])
        for index, expected in {52: "430030", 53: "501f00", 203: "303511", 227: "382120",
                                238: "300200", 239: "3006ff", 240: "471303", 241: "440701", 250: "301900"}.items():
            self.assertEqual(words[index], expected)
        source = ROOT / "board/vendor/ZYNQ_Vitis_7020/44_ov5640_ps_eth_udp_pc/vitis/ov5640_ps_eth_udp_pc/src/ov5640/ov5640_init.c"
        if source.is_file():
            raw = source.read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),
                "1152ebabd1d6e5b8cdd4ac5208acbe2e6807aea8e57132f7ce77316342839e4b")
            expected = []
            for addr, value in re.findall(r"sccb_write_reg16\(0x([0-9a-fA-F]{4}),\s*([^;]+?)\);", raw.decode("gbk")):
                if (addr.lower(), value.strip().lower()) in (("3016", "0x02"), ("301c", "0x02"), ("3019", "0x02")):
                    continue  # Flash-on demonstration, not camera initialization.
                data = int(value.strip(), 16) if value.strip().startswith("0x") else 0
                expected.append(f"{addr.lower()}{data:02x}")
            self.assertEqual(words, expected)

    def simulate(self, name, marker):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "test.vvp"
            subprocess.run([tool("iverilog"), "-g2012", "-Wall", "-s", name,
                "-o", str(output), *map(str, sorted((ROOT / "src/rtl/camera").glob("*.sv"))),
                str(ROOT / "sim/tb/ov5640_model.sv"), str(ROOT / f"sim/tb/{name}.sv")],
                check=True, cwd=ROOT)
            result = subprocess.run([tool("vvp"), str(output)], check=True,
                                    capture_output=True, text=True, timeout=60, cwd=ROOT)
            self.assertIn(marker, result.stdout)

    def test_sccb_pins(self):
        self.simulate("tb_sccb_master", "SCCB_PASS")

    def test_camera_configuration(self):
        self.simulate("tb_ov5640_ctrl", "OV5640_CTRL_PASS boots=20 writes=251 readbacks=16")

    def test_board_probe_mapping(self):
        self.simulate("tb_ov5640_probe", "OV5640_PROBE_PASS")
        if os.name == "nt":
            shell = shutil.which("pwsh") or shutil.which("powershell")
            self.assertIsNotNone(shell, "Windows PowerShell required for probe runner check")
            with tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                fake = work / "Vivado/bin/xsdb.bat"
                fake.parent.mkdir(parents=True)
                fake.write_text("@echo off\necho M02 camera configuration failed\nexit /b 0\n")
                result = subprocess.run([shell, "-NoProfile", "-File", str(ROOT / "prj/run_m02_jtag.ps1"),
                    "-ToolRoot", str(work), "-LogPath", str(work / "failure.log")], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, "Do not accept xsdb's zero exit after a Tcl error")


if __name__ == "__main__":
    unittest.main(verbosity=2)
