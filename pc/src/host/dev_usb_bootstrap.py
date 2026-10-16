"""Explicit trusted-local-USB development provisioning, not production security."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import struct
import time

from install_data import reject_links
from private_acl import private_acl
import relay

HEADER = struct.Struct('!4sBBHHH')
OUTER = struct.Struct('!BH')
TOTAL = 1696
SECRET_KEY_SIZE = 1632
QUERY, DATA, STATUS = 1, 2, 0x81
WAIT, RECV, READY, FAULT = range(4)
ZERO_PIN = bytes(32)


def erase(buffer):
    if buffer is not None:
        buffer[:] = b'\0' * len(buffer)


def write_record(device, kind, offset, body, deadline):
    packet = bytearray(OUTER.size + HEADER.size + len(body))
    try:
        OUTER.pack_into(packet, 0, 1, HEADER.size + len(body))
        HEADER.pack_into(packet, OUTER.size, b'EYBS', 1, kind, offset, len(body), TOTAL)
        packet[OUTER.size + HEADER.size:] = body
        sent = 0
        while sent < len(packet):
            if time.monotonic() >= deadline:
                raise TimeoutError('development bootstrap write deadline')
            count = device.write(memoryview(packet)[sent:])
            if count is None or not 0 < count <= len(packet) - sent:
                raise OSError('development bootstrap short write')
            sent += count
    finally:
        erase(packet)


def read_exact(device, size, deadline):
    result = bytearray()
    while len(result) < size:
        if time.monotonic() >= deadline:
            raise TimeoutError('development bootstrap response deadline')
        part = device.read(size - len(result))
        if len(part) > size - len(result):
            raise ValueError('development bootstrap oversized response')
        result.extend(part)
    return result


def status(device, deadline):
    channel, length = OUTER.unpack(read_exact(device, OUTER.size, deadline))
    if channel != 1 or length != HEADER.size + 34:
        raise ValueError('development bootstrap status framing')
    payload = read_exact(device, length, deadline)
    magic, version, kind, offset, length, total = HEADER.unpack_from(payload)
    state, code = payload[HEADER.size:HEADER.size + 2]
    pin = payload[HEADER.size + 2:]
    if (magic != b'EYBS' or version != 1 or kind != STATUS or length != 34 or total != TOTAL
            or code != 0 or state not in (WAIT, RECV, READY)
            or (state == WAIT and (offset != 0 or pin != ZERO_PIN))
            or (state == RECV and (not 0 < offset < TOTAL or pin != ZERO_PIN))
            or (state == READY and offset != TOTAL)):
        raise ValueError('development bootstrap rejected status')
    return state, offset, pin


def private_material(path, expected_public, expected_pin):
    path = Path(os.path.abspath(os.fspath(path)))
    if str(path).startswith(('\\\\', '//')):
        raise ValueError('development identity must be a local file')
    reject_links(path)
    path = path.resolve(strict=True)
    private_acl(path.parent)
    private_acl(path)
    key = bytearray(SECRET_KEY_SIZE + 1)
    try:
        with path.open('rb', buffering=0) as source:
            if source.readinto(key) != SECRET_KEY_SIZE:
                raise ValueError('development identity size')
        public = memoryview(key)[768:1568]
        pin = hashlib.sha256(public).digest()
        if (not hmac.compare_digest(public, expected_public)
                or not hmac.compare_digest(pin, expected_pin)
                # FIPS 203 H(ek) is SHA3-256, distinct from the application's SHA256 pin.
                or not hmac.compare_digest(memoryview(key)[1568:1600], hashlib.sha3_256(public).digest())):
            raise ValueError('development identity does not match public pairing')
        return key
    except BaseException:
        erase(key)
        raise


def provision(device, identity_file, expected_public, expected_pin):
    key = seed = material = None
    try:
        key = private_material(identity_file, expected_public, expected_pin)
        seed = bytearray(secrets.token_bytes(32))
        if len(seed) != 32:
            raise ValueError('development seed size')
        material = bytearray(TOTAL)
        material[:32] = expected_pin
        material[32:1664] = memoryview(key)[:SECRET_KEY_SIZE]
        material[1664:] = seed
        deadline = time.monotonic() + 10.0
        for offset in range(0, TOTAL, 1024):
            end = min(TOTAL, offset + 1024)
            write_record(device, DATA, offset, memoryview(material)[offset:end], deadline)
            state, accepted, pin = status(device, min(deadline, time.monotonic() + 2.0))
            wanted = READY if end == TOTAL else RECV
            if (state != wanted or accepted != end
                    or not hmac.compare_digest(pin, expected_pin if wanted == READY else ZERO_PIN)):
                raise ValueError('development bootstrap acknowledgement mismatch')
    finally:
        # Best effort for owned Python buffers; driver/native/immutable temporary copies are not guaranteed erased.
        erase(key)
        erase(seed)
        erase(material)


def close_device(device):
    try:
        device.dtr = False
        device.reset_input_buffer()
        device.reset_output_buffer()
    finally:
        device.close()


def open_bootstrapped(port, identity_file, pairing_file, *, opener=None):
    if not isinstance(port, str) or not port or port.lower() == 'auto':
        raise ValueError('development bootstrap requires an explicit serial port')
    public_pairing = json.loads(relay.read_pairing(pairing_file))
    expected_public = bytes.fromhex(public_pairing['public_key_hex'])
    expected_pin = bytes.fromhex(public_pairing['public_key_sha256'])
    device = (opener or relay.open_cdc)(port)
    try:
        device.dtr = False
        device.reset_input_buffer()
        device.reset_output_buffer()
        time.sleep(0.25)
        device.reset_input_buffer()
        device.dtr = True
        deadline = time.monotonic() + 2.0
        write_record(device, QUERY, 0, b'', deadline)
        state, _, pin = status(device, deadline)
        if state == WAIT:
            provision(device, identity_file, expected_public, expected_pin)
        elif state != READY or not hmac.compare_digest(pin, expected_pin):
            raise ValueError('development bootstrap not ready or public pin mismatch')
        return device
    except BaseException:
        close_device(device)
        raise
