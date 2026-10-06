"""M03 actual PCLK/HREF/VSYNC simulation, using an owned real JPEG and byte scoreboard."""
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_m02 import tool
from iverilog_runner import compile_iverilog

ROOT = Path(__file__).resolve().parents[2]
# Own 16x16 RGB gradient, encoded once with the installed Pillow. No runtime image dependency.
JPEG = base64.b64decode(
    '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwg'
    'JC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIy'
    'MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAQABADASIAAhEBAxEB/8QA'
    'HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIh'
    'MUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVW'
    'V1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG'
    'x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQF'
    'BgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAV'
    'YnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE'
    'hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq'
    '8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDzew0Py8fJ/wDWrtbDQvLx8v8A9aulsNC8vHyf/WrXsNC8vHyf'
    '/Woxea/2V1vf5ctvvve/y/I4fzvntqf/2Q=='
)


def jpeg_length(data):
    """Independent software marker walk; header payload/trailing file bytes are not markers."""
    if not data.startswith(b'\xff\xd8'):
        raise ValueError('Missing SOI')
    position, scan = 2, False
    while position < len(data):
        if scan:
            position = data.find(b'\xff', position)
            if position < 0:
                break
        if data[position] != 255:
            raise ValueError('Expected JPEG marker')
        while position < len(data) and data[position] == 255:
            position += 1
        if position == len(data):
            break
        marker = data[position]
        position += 1
        if scan and (marker == 0 or 0xd0 <= marker <= 0xd7 or marker == 1):
            continue
        if marker == 0xd9:
            return position
        if marker == 1:
            continue
        if marker in (0, 0xd8) or position + 2 > len(data):
            raise ValueError('Invalid/truncated JPEG marker')
        size = int.from_bytes(data[position:position + 2], 'big')
        if size < 2 or position + size > len(data):
            raise ValueError('Invalid/truncated JPEG segment')
        position += size
        scan = marker == 0xda
    raise ValueError('Missing EOI')


def simulate(jpeg, *, frames=1000, faults=True, limit=4096):
    length = jpeg_length(jpeg)
    if length > limit or len(jpeg) > 2 * 1024 * 1024:
        raise ValueError('JPEG exceeds simulation frame/input limit')
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        data, executable = work / 'jpeg.mem', work / 'test.vvp'
        data.write_text(''.join(f'{byte:02x}\n' for byte in jpeg))
        compile_iverilog([tool('iverilog'), '-g2012', '-Wall', '-s', 'tb_dvp_capture',
            f'-Ptb_dvp_capture.MAX_FRAME_BYTES={limit}', '-o', str(executable),
            str(ROOT / 'src/rtl/camera/jpeg_marker_check.sv'),
            str(ROOT / 'src/rtl/camera/dvp_capture.sv'), str(ROOT / 'sim/tb/tb_dvp_capture.sv')], executable)
        result = subprocess.run([tool('vvp'), str(executable), f'+JPEG={data}', f'+JPEG_LENGTH={length}',
            f'+INPUT_LENGTH={len(jpeg)}',
            f'+FRAMES={frames}', f'+FAULTS={int(faults)}'], text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        if f'DVP_REPLAY_PASS frames={frames} bytes={length}' not in result.stdout:
            raise AssertionError('Missing replay evidence: ' + result.stdout)
        if faults and 'DVP_FAULT_PASS' not in result.stdout:
            raise AssertionError('Missing fault recovery evidence: ' + result.stdout)
        return result.stdout


class M03(unittest.TestCase):
    def test_dvp_frames_and_recovery(self):
        self.assertEqual(len(JPEG), 685)
        self.assertEqual(hashlib.sha256(JPEG).hexdigest(),
                         'e12f916f67a6643388ecd3dff76cdf8120741984f1d67dc557d80100fc363bd3')
        print(simulate(JPEG), end='')

    def test_header_marker_bytes_and_real_input(self):
        # APP/COM payload is length-delimited: these FF D8/FF D9 bytes are NOT frame boundaries.
        payload = bytes.fromhex('ffd8ffd9ff00ffd00001')
        segment = b'\xff\xe1' + (len(payload) + 2).to_bytes(2, 'big') + payload
        comment = b'\xff\xfe\x00\x06\xff\xd9\xff\xd8'
        jpeg = JPEG[:2] + segment + comment + JPEG[2:]
        self.assertEqual(jpeg_length(jpeg + b'\x00\xff\xd9'), len(jpeg))
        for malformed in (b'', JPEG[:-2], b'\xff\xd8\xff\xe1\x00\x01'):
            with self.assertRaises(ValueError):
                jpeg_length(malformed)
        print(simulate(jpeg, frames=4, faults=False), end='')
        # Optional local user JPEG; ordinary clean checkout/hook does not depend on personal files.
        if source := os.environ.get('M03_REAL_JPEG'):
            path = Path(source)
            with path.open('rb') as file:
                real = file.read(2 * 1024 * 1024 + 1)
            print(simulate(real, frames=3, faults=False, limit=2 * 1024 * 1024), end='')
            length = jpeg_length(real)
            print('M03_REAL_INPUT', len(real), hashlib.sha256(real).hexdigest(),
                  'jpeg_bytes=', length, 'ignored_trailing_bytes=', len(real)-length,
                  'jpeg_sha256=', hashlib.sha256(real[:length]).hexdigest())


if __name__ == '__main__':
    unittest.main(verbosity=2)
