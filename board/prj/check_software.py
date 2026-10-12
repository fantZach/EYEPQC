"""Run all computer-only regression gates and preserve logs plus a JSON summary."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
TESTS = ['test_m00.py', 'test_aes_mvp.py', 'test_m01.py', 'test_m02.py',
         'test_m03.py', 'test_m04.py', 'test_m05.py', 'test_m07.py',
         'test_m08.py', 'test_m09.py', 'test_m10.py', 'test_m12.py',
         'test_g3.py', 'test_g5.py', 'test_g6.py', 'test_usb_recovery.py', 'test_demo.py']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool-root', type=Path, default=os.environ.get('EYEPQC_TOOL_ROOT', 'E:/fpg/2026.1'))
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / 'build/software_checks' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')).resolve()
    if output.exists():
        parser.error('Use a fresh results directory')
    output.mkdir(parents=True)
    env = os.environ.copy()
    env['VIVADO_ROOT'] = str(args.tool_root.resolve() / 'Vivado')
    if os.name == 'nt' and Path('C:/msys64/ucrt64/bin').is_dir():
        env['PATH'] = 'C:/msys64/ucrt64/bin;' + env['PATH']
    env.setdefault('CC', shutil.which('gcc', path=env['PATH']) or 'gcc')
    env['PYTHONUTF8'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    commands = [('dependencies', [sys.executable, 'board/prj/check_dependencies.py']),
                ('vectors', [sys.executable, 'sim/scripts/generate_vectors.py', '--check'])]
    commands += [(name.removesuffix('.py'), [sys.executable, 'sim/tb/' + name]) for name in TESTS]
    result = dict(python=sys.version, compiler=env['CC'], vivado_root=env['VIVADO_ROOT'],
                  board_accessed=False, tests=[], status='RUNNING')
    for name, command in commands:
        print('CHECK', name, flush=True)
        started = time.monotonic()
        with (output / (name + '.log')).open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                code = process.wait(timeout=600)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                else:
                    process.kill()
                process.wait()
                code = -1
                log.write('\nCHECK TIMEOUT\n')
        result['tests'].append(dict(name=name, returncode=code, seconds=round(time.monotonic() - started, 3),
                                    log=name + '.log', status='PASS' if code == 0 else 'FAIL'))
        result['status'] = 'FAIL' if code else 'RUNNING'
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        if code:
            print('SOFTWARE_CHECK_FAIL', name, 'log=', output / (name + '.log'), flush=True)
            raise SystemExit(1)
        print('PASS', name, flush=True)
    result['status'] = 'PASS'
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'SOFTWARE_CHECK_OK gates={len(commands)} results={output}', flush=True)


if __name__ == '__main__':
    main()
