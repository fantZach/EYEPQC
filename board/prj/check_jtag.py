"""Check target enumeration without resetting, downloading, or accessing board memory."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-root', type=Path, required=True)
    args = parser.parse_args()
    xsdb = args.tool_root / 'Vivado/bin/xsdb.bat'
    if not xsdb.is_file():
        parser.error('XSDB not found: ' + str(xsdb))
    folder = ROOT / 'build/jtag_checks' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    folder.mkdir(parents=True)
    with subprocess.Popen([str(xsdb), str(ROOT / 'board/prj/check_jtag.tcl')],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, errors='replace') as process:
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                               check=False, capture_output=True)
            else:
                process.kill()
            stdout, stderr = process.communicate(timeout=10)
            stderr += '\nJTAG_CHECK_TIMEOUT\n'
    text = stdout + stderr
    log = folder / 'targets.log'
    log.write_text(text, encoding='utf-8')
    print(text.strip())
    print('JTAG_LOG', log)
    # Windows XSDB launchers can mask Tcl exit(1).
    if process.returncode or 'JTAG_CHECK_OK' not in stdout or 'JTAG_CHECK_TIMEOUT' in stderr:
        print('JTAG is not ready. Restore board power/reset/boot mode and restart hw_server; '
              'do not run G3 until APU and Cortex-A9#0 are visible.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
