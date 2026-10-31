"""Prepare an explicit deployment CA/IP certificate offline; never starts services."""
import argparse
import datetime as dt
import ipaddress
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from install_data import reject_links
from prepare_pairing import _new_file
from prepare_test_tls import certificate, pem_key
from private_acl import private_acl


def local_path(path):
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('an absolute local path is required')
    reject_links(path)
    return path


def load_issuer(directory, now):
    directory = local_path(directory)
    private_acl(directory / 'private')
    key_path = directory / 'private/ca-key.pem'
    cert_path = directory / 'public/ca.pem'
    reject_links(key_path)
    reject_links(cert_path)
    private_acl(key_path)
    if not 0 < key_path.stat().st_size <= 32768 or not 0 < cert_path.stat().st_size <= 131072:
        raise ValueError('issuer input missing or oversized')
    ca = x509.load_pem_x509_certificate(cert_path.read_bytes())
    signer = serialization.load_pem_private_key(key_path.read_bytes(), None)
    try:
        constraint = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
        usage = ca.extensions.get_extension_for_class(x509.KeyUsage).value
        if (not constraint.ca or not usage.key_cert_sign or not isinstance(signer, rsa.RSAPrivateKey)
                or signer.key_size < 2048 or not isinstance(ca.signature_hash_algorithm, (hashes.SHA256, hashes.SHA384, hashes.SHA512))
                or ca.not_valid_before_utc > now or ca.not_valid_after_utc <= now + dt.timedelta(hours=1)
                or ca.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
                != signer.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)):
            raise ValueError('unsuitable issuer')
        ca.verify_directly_issued_by(ca)
    except (x509.ExtensionNotFound, TypeError) as error:
        raise ValueError('issuer must be a suitable self-signed deployment CA') from error
    return ca, signer


def prepare(output, ip, *, ca_dir=None, ca_days=3650, leaf_days=365):
    output = local_path(output)
    ip = ipaddress.IPv4Address(ip)
    if type(ca_days) is not int or not 1 <= ca_days <= 3650 or type(leaf_days) is not int or not 1 <= leaf_days <= 397:
        raise ValueError('invalid CA/leaf lifetime')
    if output.exists():
        raise FileExistsError('choose a new issuer output directory')
    if not output.parent.is_dir():
        raise FileNotFoundError('issuer output parent must exist')
    now = dt.datetime.now(dt.timezone.utc)
    ca = signer = None
    if ca_dir is not None:
        ca, signer = load_issuer(ca_dir, now)
    output.mkdir(mode=0o700)
    private = output / 'private'
    public = output / 'public'
    directories, files = [output], []
    try:
        private.mkdir(mode=0o700)
        directories.append(private)
        private_acl(private, protect=True)
        public.mkdir(mode=0o755)
        directories.append(public)
        if ca is None:
            signer = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'EYEPQC deployment CA')])
            ca = certificate(signer, name, name, signer, now, now + dt.timedelta(days=ca_days), ca=True)
        server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(ip))])
        leaf = certificate(server_key, server_name, ca.subject, signer, now,
                           min(now + dt.timedelta(days=leaf_days), ca.not_valid_after_utc), ca=False, ips=[ip])
        ca_pem = ca.public_bytes(serialization.Encoding.PEM)
        payloads = [(public / 'ca.pem', ca_pem, 0o644),
                    (public / 'server-chain.pem', leaf.public_bytes(serialization.Encoding.PEM) + ca_pem, 0o644),
                    (private / 'server-key.pem', pem_key(server_key), 0o600)]
        if ca_dir is None:
            payloads.append((private / 'ca-key.pem', pem_key(signer), 0o600))
        for path, data, mode in payloads:
            _new_file(path, data, mode)
            files.append(path)
            if path.read_bytes() != data:
                raise OSError('certificate material readback mismatch')
            if path.parent == private:
                private_acl(path)
        summary = dict(prepared=True, services_started=False, ca_created=ca_dir is None, ip=str(ip),
                       ca_sha256=ca.fingerprint(hashes.SHA256()).hex(),
                       leaf_sha256=leaf.fingerprint(hashes.SHA256()).hex(),
                       ca_expires_utc=ca.not_valid_after_utc.isoformat(),
                       leaf_expires_utc=leaf.not_valid_after_utc.isoformat())
        summary_path = output / 'prepared.json'
        _new_file(summary_path, (json.dumps(summary, indent=2) + '\n').encode(), 0o644)
        files.append(summary_path)
        return summary
    except Exception:
        # Remove only this invocation's known files; unexpected/nonempty paths are never wiped.
        for path in reversed(files):
            path.unlink()
        for directory in reversed(directories):
            directory.rmdir()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--ip', required=True)
    parser.add_argument('--ca-dir', type=Path, help='Explicit existing protected deployment CA; never altered')
    parser.add_argument('--ca-days', type=int, default=3650)
    parser.add_argument('--leaf-days', type=int, default=365)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.output_dir, args.ip, ca_dir=args.ca_dir,
                                 ca_days=args.ca_days, leaf_days=args.leaf_days), indent=2))
        return 0
    except Exception:
        print('DEPLOYMENT_TLS_ERROR: preparation refused; check new local output, issuer permissions, key match and validity')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
