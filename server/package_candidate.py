"""Create a public-source-only Server candidate; never contacts or configures a host."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
VERSION = '1.0.0-rc1'
FILES = ('prepare_tunnel.py', 'eyepqc-tunnel.service', 'DEPLOYMENT.md', 'DEPLOYMENT_ADVANCED.md',
         'package_candidate.py', 'tests/test_prepare_tunnel.py', 'tests/test_package_candidate.py')


def regular_path(value):
    if str(value).startswith(('\\\\', '//')):
        raise ValueError('Use a local path, not a network share')
    path = Path(os.path.abspath(value))
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, 'is_junction') and item.is_junction()):
            raise ValueError('Candidate paths must not traverse links or junctions')
    return path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package(output):
    output = regular_path(output)
    if output.suffix.lower() != '.zip' or not output.parent.is_dir():
        raise ValueError('Use a new ZIP file in an existing local directory')
    if output.exists():
        raise FileExistsError('Candidate exists; never overwrite a previous package')
    # Never walk the directory: runtime configs/keys placed beside these sources are excluded.
    files = {name: regular_path(ROOT / name).read_bytes() for name in FILES}
    manifest = {
        'component': 'server', 'version': VERSION, 'delivery': 'source-only',
        'user_acceptance': 'pending', 'linux_sshd_validated': False,
        'systemd_validated': False, 'public_network_validated': False,
        'deployment_performed': False, 'runtime_keys_or_configuration_included': False,
        'requirements': 'Python 3.10+, systemd Linux, compatible OpenSSH /usr/sbin/sshd',
        'source_sha256': {name: digest(data) for name, data in sorted(files.items())},
    }
    files['manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode('utf-8')
    files['SHA256SUMS.txt'] = ''.join(digest(data) + '  ' + name + '\n'
                                    for name, data in sorted(files.items())).encode('ascii')
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    data = buffer.getvalue()
    with output.open('xb') as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    return {'component': 'server', 'version': VERSION, 'sha256': digest(data),
            'bytes': len(data), 'user_acceptance': 'pending', 'deployment_performed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(package(args.output), indent=2))
        return 0
    except (OSError, ValueError):
        print('SERVER_PACKAGE_ERROR: source/path/output checks failed; no deployment performed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
