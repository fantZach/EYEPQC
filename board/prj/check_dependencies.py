"""Check the pinned runtime without requiring pip in a uv-created environment."""
from importlib import import_module, metadata
from pathlib import Path
import sys

if sys.version_info < (3, 12):
    raise SystemExit('Python 3.12 or newer required')
requirements = Path(__file__).resolve().parents[2] / 'requirements.txt'
for line in requirements.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    name, required = line.split('==')
    actual = metadata.version(name)
    if actual != required:
        raise SystemExit(f'{name}: required {required}, installed {actual}')
for module in ('cryptography.hazmat.primitives.ciphers.aead', 'kyber_py', 'cffi',
               'pycparser', 'PIL.Image', 'serial', 'tkinter'):
    import_module(module)
print('DEPENDENCIES_PASS pinned_versions imports python312 tkinter')
