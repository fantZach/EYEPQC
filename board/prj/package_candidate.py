"""Export a local-use, unaccepted SD candidate; never touches hardware or media."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'pc/src/host'))
from build_manifest import verify

PROFILE = 'development_usb_bootstrap_secure_cleanup'
BOOT = 'g6_usb/boot/BOOT.BIN'
LICENSES = {
    'licenses/secworks_aes.txt': 'board/src/rtl/crypto/secworks_aes/LICENSE',
    'licenses/mlkem_native.txt': 'board/src/third_party/mlkem/LICENSE',
    'licenses/tinycrypt.txt': 'board/src/third_party/tinycrypt/LICENSE',
}


def regular_path(path, *, directory=False):
    """Reject linked/reparse paths before resolving local inputs or outputs."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('Linked paths are not candidate inputs or outputs')
    if directory and not path.is_dir():
        raise ValueError('Expected an existing directory')
    return path


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def package(workspace, output):
    workspace = regular_path(workspace, directory=True)
    output = regular_path(output)
    regular_path(output.parent, directory=True)
    if output.suffix.lower() != '.zip' or output.is_relative_to(workspace):
        raise ValueError('Use a new ZIP outside the build workspace')
    if output.exists():
        raise FileExistsError('Candidate output already exists; never overwrite it')
    # A historical PASS file is insufficient: recheck real source/BSP/generated inputs now.
    result = subprocess.run([sys.executable, str(ROOT / 'board/prj/verify_software.py'),
                             str(workspace)], cwd=ROOT, capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('Software verification failed; inspect the workspace locally')
    summary = json.loads((workspace / 'software_build.json').read_text(encoding='utf-8'))
    checked = json.loads((workspace / 'software_verification.json').read_text(encoding='utf-8'))
    manifest, count = verify(workspace, 'g6_usb_manifest.json')
    if (summary.get('applications') != ['g6_usb'] or summary.get('boot_images') is not True or
            summary.get('g6_dev_usb_bootstrap') is not True or
            summary.get('board_validated') is not False or
            manifest.get('application') != 'g6_usb' or manifest.get('security_profile') != PROFILE or
            manifest.get('board_validated') is not False or
            manifest.get('development_provisioning_required') is not True or
            manifest.get('usb_bootstrap', {}).get('identity_or_seed_embedded') is not False or
            checked.get('status') != 'PASS' or checked.get('board_accessed') is not False or
            checked.get('board_validated') is not False or checked.get('bsp_lookup') != 'PASS' or
            checked.get('arm_startup') != {'g6_usb': 'PASS', 'fsbl': 'PASS'} or
            checked.get('hash_checks') != {'g6_usb': count} or
            checked.get('generated_input_checks') != len(summary.get('generated_inputs', {}))):
        raise ValueError('Expected a verified, unaccepted USB-bootstrap SD development build')
    boot = regular_path(workspace / BOOT).read_bytes()
    if not boot or sha256(boot) != manifest['artifacts'].get(BOOT):
        raise ValueError('BOOT changed after verification; rebuild or recheck first')
    for digest in (manifest['xsa_sha256'], manifest['bsp_sha256']):
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError('Invalid input digest')
    files = {'BOOT.BIN': boot, 'DEPLOYMENT.md': (ROOT / 'board/DEPLOYMENT.md').read_bytes(),
             'THIRD_PARTY_NOTICES.md': (ROOT / 'board/THIRD_PARTY_NOTICES.md').read_bytes()}
    files.update({name: (ROOT / source).read_bytes() for name, source in LICENSES.items()})
    # AMD links Vitis/data internally; resolve its read-only notice within the trusted install.
    sdk_root = Path(summary['tool_root']).resolve(strict=True)
    sdk_license = (sdk_root / 'Vitis/data/embeddedsw/license.txt').resolve(strict=True)
    if not sdk_license.is_relative_to(sdk_root):
        raise ValueError('SDK notice must remain inside its tool installation')
    sdk_license = regular_path(sdk_license)
    files['licenses/amd_embeddedsw.txt'] = sdk_license.read_bytes()
    public = {
        'component': 'board', 'target': 'CF7020B / XC7Z020 / OV5640',
        'security_profile': PROFILE, 'development_only': True,
        'user_acceptance': 'pending', 'board_validated': False,
        'local_use_only': True, 'external_redistribution_license_review': 'pending',
        'identity_or_seed_embedded': False, 'first_usb_query_hardware_fix_verified': False,
        'software_checks': {'status': 'PASS', 'hash_checks': count,
                            'generated_inputs': checked['generated_input_checks'],
                            'bsp_lookup': 'PASS', 'arm_startup': checked['arm_startup']},
        'boot_sha256': sha256(boot), 'boot_bytes': len(boot),
        'xsa_sha256': manifest['xsa_sha256'], 'bsp_sha256': manifest['bsp_sha256'],
        'source_manifest_sha256': sha256((workspace / 'g6_usb_manifest.json').read_bytes()),
    }
    files['manifest.json'] = (json.dumps(public, indent=2) + '\n').encode('utf-8')
    files['SHA256SUMS.txt'] = ''.join(sha256(data) + '  ' + name + '\n'
                                    for name, data in sorted(files.items())).encode('ascii')
    # Fixed allowlist only: never traverse the workspace or copy its private files/manifests.
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
    payload = buffer.getvalue()
    with output.open('xb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return {'status': 'LOCAL_CANDIDATE_READY', 'sha256': sha256(payload),
            'bytes': len(payload), 'user_acceptance': 'pending', 'board_accessed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(package(args.workspace, args.output), indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('BOARD_PACKAGE_ERROR: checks failed or output exists; no media was changed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
