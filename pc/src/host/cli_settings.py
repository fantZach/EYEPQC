"""Public parameters and local paths only; no credential contents."""
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
import tempfile

FILES = ('accounts_file', 'pairing_file', 'tls_cert', 'tls_key')
TUNNEL_FILES = ('identity_file', 'known_hosts')
FIELDS = {'version', 'serial_port', *FILES, 'tunnel'}
TUNNEL_FIELDS = {'enabled', 'host', 'ssh_port', *TUNNEL_FILES}
KEYS = ('serial_port', *FILES, *(f'tunnel.{key}' for key in ('enabled', 'host', 'ssh_port', *TUNNEL_FILES)))


def executable_dir():
    return Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]


def settings_path():
    value = os.environ.get('LOCALAPPDATA', '')
    path = Path(value)
    if (not value or not path.is_absolute() or str(path).startswith(('\\\\', '//'))
            or any(ord(c) < 32 for c in value)):
        raise ValueError('LOCALAPPDATA must be an absolute local directory')
    target = path.resolve()
    if str(target).startswith(('\\\\', '//')):
        raise ValueError('LOCALAPPDATA must resolve to a local directory')
    return target / 'EYEPQC/pc/settings.json'


def read_json(path):
    with Path(path).open('rb') as source:
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ValueError('configuration exceeds 16 KiB')

    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate configuration field')
            out[key] = value
        return out

    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=unique)


def local_file(value, base, *, ssh=False):
    if (not isinstance(value, str) or not value.strip() or value.startswith(('\\\\', '//'))
            or any(ord(c) < 32 for c in value)
            or (ssh and any(c in value for c in ('"', '%', '$')))):
        raise ValueError('configuration paths must name literal local files')
    target = (base / value).resolve()
    if str(target).startswith(('\\\\', '//')) or (ssh and any(c in str(target) for c in ('"', '%', '$'))):
        raise ValueError('configuration paths must resolve to local files')
    return str(target)


def normalize(record, base, *, legacy=False, retained_tunnel=None):
    if (not isinstance(record, dict) or set(record) != FIELDS or type(record['version']) is not int
            or record['version'] != 1):
        raise ValueError('invalid configuration fields/version')
    config = copy.deepcopy(record)
    port = config['serial_port']
    if port is not None and (not isinstance(port, str) or not port or len(port) > 128
                            or any(ord(c) < 32 for c in port)):
        raise ValueError('invalid serial port')
    for key in FILES:
        config[key] = local_file(config[key], base)
    tunnel = config['tunnel']
    if legacy:
        if tunnel is None:
            tunnel = copy.deepcopy(retained_tunnel if retained_tunnel is not None else default_record()['tunnel'])
            tunnel['enabled'] = False
        elif isinstance(tunnel, dict) and set(tunnel) == TUNNEL_FIELDS - {'enabled'}:
            tunnel = dict(tunnel, enabled=True)
        else:
            raise ValueError('invalid legacy tunnel fields')
    if (not isinstance(tunnel, dict) or set(tunnel) != TUNNEL_FIELDS or type(tunnel['enabled']) is not bool
            or type(tunnel['ssh_port']) is not int or not 1 <= tunnel['ssh_port'] <= 65535):
        raise ValueError('invalid tunnel fields')
    host = tunnel['host']
    if (not isinstance(host, str) or not host or len(host) > 253 or
            not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) for part in host.split('.'))):
        raise ValueError('invalid SSH host')
    if all(part.isdigit() for part in host.split('.')):
        ipaddress.IPv4Address(host)
    for key in TUNNEL_FILES:
        tunnel[key] = local_file(tunnel[key], base, ssh=True)
    config['tunnel'] = tunnel
    return config


def default_record():
    return dict(version=1, serial_port=None, accounts_file='private/accounts.json',
        pairing_file='public/pairing.json', tls_cert='public/server-chain.pem', tls_key='private/server-key.pem',
        tunnel=dict(enabled=True, host='203.0.113.10', ssh_port=22022,
                    identity_file='private/id_ed25519', known_hosts='public/tunnel_known_hosts'))


def defaults():
    return normalize(default_record(), settings_path().parent / 'data')


def effective():
    path = settings_path()
    return normalize(read_json(path), path.parent) if path.exists() else defaults()


def persist(config):
    path = settings_path()
    # Validate existing state again before replacing it; never silently reset corruption.
    if path.exists():
        normalize(read_json(path), path.parent)
    config = normalize(config, executable_dir())
    data = (json.dumps(config, indent=2) + '\n').encode('utf-8')
    if len(data) > 16384:
        raise ValueError('configuration exceeds 16 KiB')
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.settings-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def set_value(key, value):
    if key not in KEYS:
        raise ValueError('unknown configuration key')
    config = effective()
    target, field = (config['tunnel'], key[7:]) if key.startswith('tunnel.') else (config, key)
    if key == 'serial_port' and value == 'auto':
        value = None
    elif key == 'tunnel.enabled':
        if value not in ('true', 'false'):
            raise ValueError('tunnel.enabled requires true or false')
        value = value == 'true'
    elif key == 'tunnel.ssh_port':
        if not re.fullmatch(r'[0-9]{1,5}', value):
            raise ValueError('SSH port must be numeric')
        value = int(value)
    elif field in FILES + TUNNEL_FILES:
        value = local_file(value, Path.cwd(), ssh=field in TUNNEL_FILES)
    target[field] = value
    persist(config)


def import_legacy(path):
    current = effective()
    source = Path(path).resolve()
    config = normalize(read_json(source), source.parent, legacy=True, retained_tunnel=current['tunnel'])
    persist(config)


def show():
    path = settings_path()
    config = effective()
    print(json.dumps(dict(source='user-settings' if path.exists() else 'built-in-defaults',
        settings_file=str(path), relay_host='127.0.0.1', relay_port=8765, config=config), indent=2))
