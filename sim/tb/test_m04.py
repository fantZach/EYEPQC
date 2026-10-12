"""M04 uses the installed AMD XPM models, not a hand-written substitute FIFO."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_m03 import JPEG

ROOT = Path(__file__).resolve().parents[2]


def vivado_tool(name):
    found = shutil.which(name)
    if found:
        return found
    root = Path(os.environ.get('VIVADO_ROOT', 'D:/AmdDesignTools/2026.1/Vivado'))
    path = root / 'bin' / (name + ('.bat' if os.name == 'nt' else ''))
    if not path.is_file():
        raise RuntimeError('Install Vivado/XSim or set VIVADO_ROOT; native XPM tests cannot be skipped')
    return str(path)


def run(command, work):
    result = subprocess.run(command, cwd=work, text=True, capture_output=True, timeout=180)
    output = result.stdout + result.stderr
    if result.returncode or re.search(r'(?im)^\s*(?:error|fatal):', output):
        raise AssertionError(output)
    return output


class M04(unittest.TestCase):
    def test_native_fifo_and_axis(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            fixture = work / 'jpeg.mem'
            fixture.write_text(''.join(f'{byte:02x}\n' for byte in JPEG))
            sources = ['board/src/rtl/common/axis_byte_packer.sv', 'board/src/rtl/camera/camera_axis_bridge.sv',
                       'board/src/rtl/camera/dvp_capture.sv', 'board/src/rtl/camera/jpeg_marker_check.sv',
                       'sim/tb/tb_camera_axis_bridge.sv']
            xvlog = vivado_tool('xvlog')
            glbl = Path(xvlog).parent.parent / 'data/verilog/src/glbl.v'
            run([xvlog, '--sv', *[str(ROOT / source) for source in sources], str(glbl)], work)
            for width, depth, top in ((32, 1024, 'tb_camera_axis_bridge32'),
                                      (64, 1024, 'tb_camera_axis_bridge64'),
                                      (32, 65536, 'tb_camera_axis_bridge_64k')):
                snapshot = f'm04_{width}_{depth}'
                run([vivado_tool('xelab'), top, 'glbl', '-L', 'xpm',
                     '-s', snapshot], work)
                output = run([vivado_tool('xsim'), snapshot, '--runall'], work)
                marker = f'CAMERA_AXIS_PASS width={width} depth={depth} jpeg_frames=1000 tails=1..17'
                self.assertIn(marker, output)
                print(next(line for line in output.splitlines() if marker in line), flush=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
