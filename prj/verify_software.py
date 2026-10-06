"""Verify software hashes and exercise AMD config lookups without any board access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/host'))
from build_manifest import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    summary = json.loads((workspace / 'software_build.json').read_text(encoding='utf-8'))
    for base, entries in ((workspace, summary.get('generated_inputs', {})),
                          (ROOT, summary.get('build_scripts', {}))):
        for relative, expected in entries.items():
            path = (base / relative).resolve()
            if not path.is_relative_to(base) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Build input changed: ' + relative)
    counts = {}
    for name in summary['applications']:
        manifest, counts[name] = verify(workspace, name + '_manifest.json')
        bsp = workspace / 'bsp/ps7_cortexa9_0'
        if hashlib.sha256((bsp / 'lib/libxil.a').read_bytes()).hexdigest() != manifest['bsp_sha256']:
            raise ValueError('BSP library changed')
    env = os.environ.copy()
    if os.name == 'nt':
        env['PATH'] = 'C:/msys64/ucrt64/bin;' + env['PATH']
    gcc = env.get('CC') or shutil.which('gcc', path=env['PATH'])
    if not gcc:
        raise RuntimeError('Native GCC required for actual BSP lookup verification')
    sources = [ROOT / 'sim/tb/test_bsp_lookup.c']
    for driver in ('axidma_v9_21', 'uartps_v3_18', 'usbps_v2_11'):
        sources += [p for p in (bsp / 'libsrc' / driver / 'src').glob('*.c')
                    if p.name.endswith(('_sinit.c', '_g.c'))]
    executable = workspace / 'bsp_lookup.exe'
    command = [gcc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(bsp / 'include'),
               '-I', str(ROOT / 'src/ps/include'), *[str(p) for p in sources], '-o', str(executable)]
    subprocess.run(command, env=env, check=True)
    output = subprocess.check_output([str(executable)], env=env, text=True)
    if 'BSP_LOOKUP_PASS' not in output:
        raise RuntimeError('BSP lookup did not pass')
    print(output.strip())
    result = dict(status='PASS', hash_checks=counts, bsp_lookup='PASS', board_accessed=False,
                  generated_input_checks=len(summary.get('generated_inputs', {})),
                  board_validated=summary['board_validated'])
    (workspace / 'software_verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('SOFTWARE_VERIFY_OK', json.dumps(counts))


if __name__ == '__main__':
    main()
