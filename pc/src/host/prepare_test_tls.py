"""Prepare short-lived debug TLS and account files; never starts a service."""

import argparse
import datetime as dt
import ipaddress
import json
import os
from pathlib import Path
import secrets
import subprocess
from private_acl import private_acl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from accounts import create_account
from prepare_pairing import _new_file, configuration


def pem_key(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def certificate(key, name, issuer, signer, now, expires, *, ca, ips=()):
    builder = (x509.CertificateBuilder().subject_name(name).issuer_name(issuer)
               .public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(now - dt.timedelta(minutes=5)).not_valid_after(expires)
               .add_extension(x509.BasicConstraints(ca=ca, path_length=0 if ca else None), True)
               .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                   key_encipherment=not ca, data_encipherment=False, key_agreement=False,
                   key_cert_sign=ca, crl_sign=ca, encipher_only=False, decipher_only=False), True)
               .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
               .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()), False))
    if not ca:
        builder = (builder.add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
                   .add_extension(x509.SubjectAlternativeName(
                       [x509.IPAddress(ip) for ip in ips] + [x509.DNSName('localhost')]), False))
    return builder.sign(signer, hashes.SHA256())


def prepare(output, identity_dir, ip='10.0.0.10', *, ca_dir=None):
    output = Path(output)
    ip = ipaddress.IPv4Address(ip)
    config = configuration(identity_dir, f'wss://{ip}:8765/stream')
    if output.exists():
        raise FileExistsError('output already exists; select a new directory')
    now = dt.datetime.now(dt.timezone.utc)
    if ca_dir is not None:
        ca_dir = Path(ca_dir)
        private_acl(ca_dir / 'private')
        private_acl(ca_dir / 'private/ca-key.pem')
        ca_pem = (ca_dir / 'public/ca.pem').read_bytes()
        ca = x509.load_pem_x509_certificate(ca_pem)
        signer = serialization.load_pem_private_key((ca_dir / 'private/ca-key.pem').read_bytes(), None)
        ca.verify_directly_issued_by(ca)
        if (not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
                or ca.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
                != signer.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
                or ca.not_valid_before_utc > now or ca.not_valid_after_utc < now + dt.timedelta(days=1)):
            raise ValueError('existing CA is unsuitable')
    output.mkdir(parents=True)
    private = output / 'private'
    private.mkdir(mode=0o700)
    try:
        private_acl(private, protect=True)  # Fail before creating any credential or private key.
    except Exception:
        private.rmdir()
        output.rmdir()
        raise
    public = output / 'public'
    public.mkdir()
    if ca_dir is None:
        signer = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'EYEPQC debug test CA')])
        ca = certificate(signer, name, name, signer, now, now + dt.timedelta(days=30), ca=True)
        ca_pem = ca.public_bytes(serialization.Encoding.PEM)
        _new_file(private / 'ca-key.pem', pem_key(signer), 0o600)
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'EYEPQC debug relay')])
    leaf = certificate(server_key, server_name, ca.subject, signer, now,
                       min(now + dt.timedelta(days=7), ca.not_valid_after_utc), ca=False,
                       ips=list(dict.fromkeys([ip, ipaddress.IPv4Address('127.0.0.1')])))
    _new_file(private / 'server-key.pem', pem_key(server_key), 0o600)
    password = secrets.token_urlsafe(32)
    create_account(private / 'accounts.json', 'viewer', password)
    _new_file(private / 'login.txt', f'username=viewer\npassword={password}\n'.encode(), 0o600)
    for path in private.iterdir():
        private_acl(path)
    _new_file(public / 'ca.pem', ca_pem, 0o644)
    _new_file(public / 'server-chain.pem', leaf.public_bytes(serialization.Encoding.PEM) + ca_pem, 0o644)
    _new_file(public / 'pairing.json', (json.dumps(config, indent=2) + '\n').encode(), 0o644)
    summary = dict(completed=True, private_acl_verified=True,
                   paths={name: str((output / name).resolve()) for name in
                          ('public/ca.pem', 'public/server-chain.pem', 'public/pairing.json',
                           'private/server-key.pem', 'private/accounts.json', 'private/login.txt')},
                   ca_sha256=ca.fingerprint(hashes.SHA256()).hex(),
                   leaf_sha256=leaf.fingerprint(hashes.SHA256()).hex(),
                   public_key_sha256=config['public_key_sha256'])
    _new_file(output / 'prepared.json', (json.dumps(summary, indent=2) + '\n').encode(), 0o644)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--identity-dir', type=Path, required=True)
    parser.add_argument('--ip', default='10.0.0.10')
    parser.add_argument('--ca-dir', type=Path, help='Reuse this existing preparation CA; write a NEW output directory')
    args = parser.parse_args()
    summary = prepare(args.output_dir, args.identity_dir, args.ip, ca_dir=args.ca_dir)
    print(json.dumps(summary, indent=2))
