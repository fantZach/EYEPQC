"""Read-only verification before loading an offline firmware build."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def verify(workspace, manifest_name='build_manifest.json'):
    workspace = Path(workspace).resolve()
    manifest = json.loads((workspace / manifest_name).read_text(encoding='utf-8'))
    count = 0
    for base, entries in ((ROOT, manifest['sources']), (workspace, manifest['artifacts'])):
        for relative, expected in entries.items():
            path = (base / relative).resolve()
            if not path.is_relative_to(base) or not path.is_file():
                raise ValueError('Missing or invalid manifest file: ' + relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                raise ValueError('Build changed; rebuild before board use: ' + relative)
            count += 1
    for relative, expected in manifest.get('bsp_inputs', {}).items():
        path = (workspace / relative).resolve()
        if not path.is_relative_to(workspace) or not path.is_file():
            raise ValueError('Missing or invalid pinned BSP input: ' + relative)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Pinned BSP input changed; rebuild before board use: ' + relative)
        count += 1
    xsa = Path(manifest['xsa'])
    if hashlib.sha256(xsa.read_bytes()).hexdigest() != manifest['xsa_sha256']:
        raise ValueError('XSA changed; rebuild before board use')
    return manifest, count + 1
