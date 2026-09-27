"""M01 offline checks: Icarus heartbeat + fragmented/failed TCP echo."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/host"))
from m01_probe import check_echo, run


class M01(unittest.TestCase):
    def test_board_reset_polarity(self):
        script = (ROOT / "prj/build_m01.tcl").read_text()
        self.assertIn("CONFIG.C_EXT_RESET_HIGH 0 CONFIG.C_AUX_RESET_HIGH 1", script)
        self.assertIn("[get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins reset_0/ext_reset_in]", script)
        self.assertIn("[get_bd_pins zero/dout] [get_bd_pins reset_0/aux_reset_in]", script)
        self.assertIn('error "Reset polarity changed:', script)

    def test_yt8521_adapter(self):
        gcc = shutil.which("gcc")
        if not gcc and os.name == "nt" and Path("C:/msys64/ucrt64/bin/gcc.exe").is_file():
            gcc = "C:/msys64/ucrt64/bin/gcc.exe"
        if not gcc:
            self.fail("A native C compiler is required for the PHY check")
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "phy_check.exe")
            subprocess.run([gcc, "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT / "src/ps/src"),
                            str(ROOT / "sim/tb/test_yt8521.c"), "-o", output], check=True)
            subprocess.run([output], check=True, capture_output=True)

    def test_heartbeat(self):
        iverilog = os.environ.get("IVERILOG") or shutil.which("iverilog")
        vvp = os.environ.get("VVP") or shutil.which("vvp")
        if os.name == "nt":
            iverilog = iverilog or ("C:/iverilog/bin/iverilog.exe" if
                                   Path("C:/iverilog/bin/iverilog.exe").is_file() else None)
            vvp = vvp or ("C:/iverilog/bin/vvp.exe" if Path("C:/iverilog/bin/vvp.exe").is_file() else None)
        if not iverilog or not vvp:
            self.fail("Install Icarus or set IVERILOG and VVP")
        with tempfile.TemporaryDirectory() as tmp:
            output = str(Path(tmp) / "heartbeat.vvp")
            subprocess.run([iverilog, "-g2012", "-s", "tb_heartbeat", "-o", output,
                            str(ROOT / "src/rtl/common/heartbeat.sv"),
                            str(ROOT / "sim/tb/tb_heartbeat.sv")], check=True)
            result = subprocess.run([vvp, output], check=True, capture_output=True, text=True)
            self.assertIn("HEARTBEAT_PASS", result.stdout)

    def test_probe(self):
        failures = []
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            server.settimeout(2)
            port = server.getsockname()[1]
            stop = threading.Event()

            def echo():
                try:
                    while not stop.is_set():
                        try:
                            conn, _ = server.accept()
                        except TimeoutError:
                            continue
                        with conn:
                            conn.settimeout(2)
                            while data := conn.recv(4096):
                                for offset in range(0, len(data), 113):
                                    conn.sendall(data[offset:offset + 113])
                except Exception as error:
                    failures.append(error)

            thread = threading.Thread(target=echo)
            thread.start()
            try:
                result = run("127.0.0.1", port, seconds=0.08, timeout=2)
                self.assertGreater(result["rounds"], 0)
                self.assertGreaterEqual(result["bytes"], 8192 + 65537)
            finally:
                stop.set()
                thread.join(3)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])

    def test_probe_rejects_corruption_eof_timeout(self):
        class BadSocket:
            def __init__(self, response): self.response = response
            def sendall(self, _): pass
            def recv(self, _):
                if isinstance(self.response, Exception): raise self.response
                return self.response
        for response, expected in [(b"X", ValueError), (b"", ConnectionError),
                                   (TimeoutError(), TimeoutError)]:
            with self.assertRaises(expected):
                check_echo(BadSocket(response), b"Y")
        for duration in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError): run("localhost", seconds=duration)


if __name__ == "__main__":
    unittest.main(verbosity=2)
