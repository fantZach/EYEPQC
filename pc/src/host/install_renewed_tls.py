"""Install the reviewed renewal from the user's normal terminal, not Codex AppData."""
import argparse
import copy
import datetime as dt
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes
import cli_settings
from install_data import reject_links
from prepare_pairing import _new_file
from private_acl import private_acl

LEAF_PIN = '0b34fd866f8e51396d47fc1afb6212c14f10a00cba82d0b18d01542fc678d0bb'
CA_PIN = '263c8c06420a2b72726d93c746766d3efd8040fe6d711af49f240ebbc1b4dc8b'
TARGET = 'tls-renewal-20261031-app'


def local(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('absolute local path required')
    reject_links(path)
    return path


def app_path():
    path = local(cli_settings.settings_path())
    resolved = path.resolve()
    parts = [part.casefold() for part in resolved.parts]
    if any(part.startswith('openai.codex_') for part in parts):
        raise ValueError('run in your original PowerShell, outside Codex AppData redirection')
    return resolved


def ensure_stopped():
    with socket.socket() as probe:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        probe.bind(('127.0.0.1', 8765))


def install(source):
    settings = app_path()
    source = local(source)
    output = local(settings.parent / TARGET)
    if output.exists():
        raise FileExistsError('renewal target exists; never overwrite it')
    ensure_stopped()
    original = settings.read_bytes()
    previous = cli_settings.effective()
    chain_path, key_path = source / 'public/server-chain.pem', source / 'private/server-key.pem'
    for path, limit in ((chain_path, 131072), (key_path, 32768)):
        local(path)
        if not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError('missing or oversized certificate material')
    private_acl(source / 'private')
    private_acl(key_path)
    chain = chain_path.read_bytes()
    if not re.fullmatch(rb'(?:\s*-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\r\n]+-----END CERTIFICATE-----){2}\s*', chain):
        raise ValueError('expected public certificates only')
    certs = x509.load_pem_x509_certificates(chain)
    if len(certs) != 2:
        raise ValueError('expected exact reviewed leaf and root')
    leaf, ca = certs
    if leaf.fingerprint(hashes.SHA256()).hex() != LEAF_PIN or ca.fingerprint(hashes.SHA256()).hex() != CA_PIN:
        raise ValueError('certificate fingerprint mismatch')
    now = dt.datetime.now(dt.timezone.utc)
    for cert in certs:
        if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
            raise ValueError('certificate is not currently valid')
    leaf.verify_directly_issued_by(ca)
    ca.verify_directly_issued_by(ca)
    if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError('issuer is not a CA')
    if ipaddress.IPv4Address('124.70.38.245') not in leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress):
        raise ValueError('wrong IP SAN')
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(chain_path, key_path)
    output.mkdir(mode=0o700)
    private, public = output / 'private', output / 'public'
    private.mkdir(mode=0o700)
    private_acl(private, protect=True)
    public.mkdir()
    # Known files only, never copy CA signing keys, accounts or an entire source tree.
    _new_file(private / 'settings.before-renewal.json', original, 0o600)
    private_acl(private / 'settings.before-renewal.json')
    _new_file(private / 'server-key.pem', key_path.read_bytes(), 0o600)
    private_acl(private / 'server-key.pem')
    _new_file(public / 'server-chain.pem', chain, 0o644)
    if (private / 'server-key.pem').read_bytes() != key_path.read_bytes() or (public / 'server-chain.pem').read_bytes() != chain:
        raise OSError('material readback mismatch')
    context.load_cert_chain(public / 'server-chain.pem', private / 'server-key.pem')
    updated = copy.deepcopy(previous)
    updated['tls_cert'], updated['tls_key'] = str(public / 'server-chain.pem'), str(private / 'server-key.pem')
    updated = cli_settings.normalize(updated, cli_settings.executable_dir())
    ensure_stopped()
    if settings.read_bytes() != original:
        raise ValueError('configuration changed concurrently; backup retained')
    cli_settings.persist(updated)
    if cli_settings.effective() != updated:
        raise OSError('configuration readback mismatch; backup retained')
    return dict(status='APP_TLS_RENEWAL_INSTALLED', services_started=False,
                ca_unchanged=True, expires_utc=leaf.not_valid_after_utc.isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.source_dir), indent=2))
        return 0
    except Exception:
        print('TLS_INSTALL_ERROR: stop relay; use original PowerShell outside Codex; verify source and new target. Existing materials/backup retained.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
