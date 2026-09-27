"""Encrypt a <=512 KiB image on PL AES / PS GHASH over JTAG; verify on host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import subprocess
import tempfile
import time
import zipfile
import zlib
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 524288
MAGIC = 0x3150564d
JOB_SIZE = LIMIT + 76


def demo_png():
    """Own deterministic RGB test image; no image library or downloaded asset."""
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    pixels = b''.join(b'\0' + b''.join(bytes((x * 4, y * 4, (x ^ y) * 4))
                                    for x in range(64)) for y in range(64))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', 64, 64, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def pack_job(image, key, nonce):
    if len(image) > LIMIT or len(key) != 16 or len(nonce) != 12:
        raise ValueError('MVP requires <=512 KiB image, 16-byte key, 12-byte nonce')
    aad = struct.pack('!4sIII', b'MVP1', 1, len(image), 0)
    request = (struct.pack('<4I', MAGIC, 0, 0, len(image)) + key + nonce + aad
               + image.ljust(LIMIT, b'\0') + bytes(16))
    return request, aad


def verify_reply(reply, image, key, nonce, aad):
    if len(reply) != JOB_SIZE: raise ValueError('truncated/oversized board reply')
    if struct.unpack('<4I', reply[:16]) != (MAGIC, 2, 0, len(image)):
        raise ValueError('board status/length mismatch')
    if reply[16:44] != bytes(28) or reply[44:60] != aad:
        raise ValueError('board key zeroization/AAD mismatch')
    ciphertext = reply[60:60 + len(image)]
    tag = reply[60 + LIMIT:]
    sealed = ciphertext + tag
    restored = AESGCM(key).decrypt(nonce, sealed, aad)
    if restored != image or sealed != AESGCM(key).encrypt(nonce, image, aad):
        raise ValueError('board result differs from independent host AES-GCM')
    # Verify authentication before releasing/writing the restored image.
    for field in ('key', 'nonce', 'aad', 'sealed', 'tag'):
        values = dict(key=key, nonce=nonce, aad=aad, sealed=sealed)
        if field == 'tag':
            data = values['sealed']; values['sealed'] = data[:-1] + bytes([data[-1] ^ 1])
        else:
            data = values[field]; values[field] = bytes([data[0] ^ 1]) + data[1:]
        try: AESGCM(values['key']).decrypt(values['nonce'], values['sealed'], values['aad'])
        except InvalidTag: pass
        else: raise ValueError('tampered ' + field + ' accepted')
    return ciphertext, tag, restored


def validate_workspace(workspace):
    manifest = json.loads((workspace / 'build_manifest.json').read_text())
    def check(path, digest):
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('source/artifact changed; rebuild: ' + str(path))
    xsa = Path(manifest['xsa']); check(xsa, manifest['xsa_sha256'])
    for path, digest in manifest['sources'].items(): check(ROOT / path, digest)
    for path, digest in manifest['artifacts'].items(): check(workspace / path, digest)
    with zipfile.ZipFile(xsa) as archive:
        for entry, path in [('m01.bit', 'aes_mvp/_ide/bitstream/m01.bit'),
                            ('ps7_init.tcl', 'aes_mvp/_ide/psinit/ps7_init.tcl')]:
            if archive.read(entry) != (workspace / path).read_bytes():
                raise ValueError('bit/init does not belong to input XSA')
    address = manifest['mailbox_address']
    if (manifest['mailbox_size'] != JOB_SIZE or not isinstance(address, int) or
        address % 64 or not 0x100000 <= address <= 0x40000000 - JOB_SIZE):
        raise ValueError('invalid owned mailbox ABI/address')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', nargs='?', type=Path, help='default: own 64x64 PNG test image')
    parser.add_argument('--workspace', type=Path, default=ROOT / 'build/vitis/aes_mvp')
    parser.add_argument('--tool-root', type=Path, default=Path('D:/AmdDesignTools/2026.1'))
    parser.add_argument('--output', type=Path, help='fresh output directory, never overwritten')
    args = parser.parse_args()
    if args.image:
        with args.image.open('rb') as file: image = file.read(LIMIT + 1)
    else: image = demo_png()
    key, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    request, aad = pack_job(image, key, nonce)
    workspace = args.workspace.resolve()
    manifest = validate_workspace(workspace) # Before touching the board.
    output = args.output or ROOT / f'data/captures/aes_mvp_{time.time_ns()}'
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory)
        request_file, reply_file = work / 'request.bin', work / 'reply.bin'
        request_file.write_bytes(request)
        result = subprocess.run([str(args.tool_root / 'Vivado/bin/xsdb.bat'),
            str(ROOT / 'prj/run_aes_mvp.tcl'), str(workspace), str(request_file),
            str(reply_file), hex(manifest['mailbox_address'])],
            text=True, capture_output=True, timeout=180)
        (output / 'jtag.log').write_text(result.stdout + result.stderr)
        # Vendor batch scripts can return zero on Tcl errors.
        if result.returncode or 'AES_MVP_JTAG_OK' not in result.stdout.splitlines():
            raise RuntimeError('JTAG failed; inspect ' + str(output / 'jtag.log'))
        ciphertext, tag, restored = verify_reply(reply_file.read_bytes(), image, key, nonce, aad)
    suffix = args.image.suffix if args.image else '.png'
    (output / ('original' + suffix)).write_bytes(image)
    (output / ('restored' + suffix)).write_bytes(restored)
    (output / 'image.aesgcm').write_bytes(aad + nonce + ciphertext + tag)
    # Demo key stays local; fresh output is Git-ignored by default. Never print it.
    with os.fdopen(os.open(output / 'key.bin', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as file:
        file.write(key)
    evidence = dict(bytes=len(image), sha256=hashlib.sha256(image).hexdigest(),
        restored_sha256=hashlib.sha256(restored).hexdigest(), tag=tag.hex(),
        nonce=nonce.hex(), mode='AES-128-GCM', aes='PL secworks/aes', ghash='PS',
        tamper_rejected=['key', 'nonce', 'aad', 'ciphertext', 'tag'],
        xsa_sha256=manifest['xsa_sha256'], artifacts=manifest['artifacts'], board_validated=True)
    (output / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('AES_IMAGE_MVP_PASS', output, 'bytes=', len(image), 'sha256=', evidence['sha256'])


if __name__ == '__main__':
    main()
