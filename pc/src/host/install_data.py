"""Explicit, offline import of six runtime files into current-user storage."""
import copy
import os
from pathlib import Path
import ssl
import stat
import subprocess

import accounts
import cli_settings
from private_acl import private_acl
import relay

# Only these six files are admitted, never a source directory or an archive.
MATERIALS = (('accounts_file', 'private/accounts.json', 65536),
             ('pairing_file', 'public/pairing.json', 8192),
             ('tls_cert', 'public/server-chain.pem', 131072),
             ('tls_key', 'private/server-key.pem', 32768),
             ('tunnel.identity_file', 'private/id_ed25519', 32768),
             ('tunnel.known_hosts', 'public/tunnel_known_hosts', 65536))


def reject_links(path):
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('installation paths must not traverse links or reparse points')


def value(config, key):
    return config['tunnel'][key[7:]] if key.startswith('tunnel.') else config[key]


def installed_config(config, root):
    result = copy.deepcopy(config)
    for key, relative, _ in MATERIALS:
        section, field = (result['tunnel'], key[7:]) if key.startswith('tunnel.') else (result, key)
        section[field] = str(root / relative)
    return result


def validate(config):
    for key, _, maximum in MATERIALS:
        source = Path(value(config, key))
        if not source.is_file() or not 0 < source.stat().st_size <= maximum:
            raise ValueError('runtime material missing or oversized')
    accounts.read_users(config['accounts_file'])
    relay.read_pairing(config['pairing_file'])
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(config['tls_cert'], config['tls_key'])
    # Parse locally, never contact a server or display the derived public key.
    for arguments in (['-y', '-P', '', '-f', config['tunnel']['identity_file']],
                      ['-l', '-f', config['tunnel']['known_hosts']]):
        result = subprocess.run(['ssh-keygen', *arguments], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        if result.returncode:
            raise ValueError('dedicated SSH identity or known_hosts format invalid')


def install(config=None):
    reject_links(Path(os.environ.get('LOCALAPPDATA', '')))
    settings = cli_settings.settings_path()
    root = settings.parent / 'data'
    reject_links(settings)
    reject_links(root)
    if config is None:
        source = cli_settings.effective()
    else:
        source_path = Path(config).resolve()
        record = cli_settings.read_json(source_path)
        if not isinstance(record, dict):
            raise ValueError('configuration must be an object')
        if record.get('tunnel') is not None and not isinstance(record['tunnel'], dict):
            raise ValueError('tunnel must be an object or legacy null')
        legacy = record.get('tunnel') is None or 'enabled' not in record.get('tunnel', {})
        source = cli_settings.normalize(record, source_path.parent, legacy=legacy)
        # Existing damaged state must not be silently replaced by a migration.
        if settings.exists():
            cli_settings.effective()
    target = installed_config(source, root)
    if root.exists():
        # Upgrades preserve accounts and identities, including changes since import.
        for _, relative, _ in MATERIALS:
            reject_links(root / relative)
        validate(target)
        private_acl(root / 'private')
        for _, relative, _ in MATERIALS:
            if relative.startswith('private/'):
                private_acl(root / relative)
        if config is not None or any(value(source, key) != value(target, key) for key, _, _ in MATERIALS):
            raise FileExistsError('user data already exists; never replace or redirect it during upgrade')
        return dict(already_installed=True, data_directory=str(root))

    validate(source)  # No destination or settings mutation until all files preflight.
    snapshots = {}
    for key, _, maximum in MATERIALS:
        with Path(value(source, key)).open('rb') as file:
            data = file.read(maximum + 1)
        if not 0 < len(data) <= maximum:
            raise ValueError('runtime material changed during preflight')
        snapshots[key] = data
    settings.parent.mkdir(parents=True, exist_ok=True)
    created_files, created_dirs = [], []
    try:
        root.mkdir()  # Exclusive: concurrent import cannot replace another writer.
        created_dirs.append(root)
        for name in ('private', 'public'):
            directory = root / name
            directory.mkdir(mode=0o700 if name == 'private' else 0o755)
            created_dirs.append(directory)
        private_acl(root / 'private', protect=True)
        for key, relative, _ in MATERIALS:
            destination = root / relative
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created_files.append(destination)
            with os.fdopen(descriptor, 'wb') as file:
                file.write(snapshots[key])
                file.flush()
                os.fsync(file.fileno())
            if destination.read_bytes() != snapshots[key]:
                raise OSError('runtime material readback mismatch')
            if relative.startswith('private/'):
                private_acl(destination)
        validate(target)  # Validate the bytes actually copied, not just the source.
        cli_settings.persist(target)
    except Exception:
        # Only our exact, exclusively-created files/directories; never recursive deletion.
        for path in reversed(created_files):
            path.unlink()
        for path in reversed(created_dirs):
            path.rmdir()
        raise
    return dict(already_installed=False, data_directory=str(root))
