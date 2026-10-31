"""Prepare local Android pairing files without loading board private material."""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
from relay import read_token


def _new_file(path, data, mode):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
    except Exception:
        Path(path).unlink()
        raise


def configuration(identity_dir, endpoint, token=None):
    endpoint = str(endpoint)
    address = urlsplit(endpoint)
    if (address.scheme not in ("ws", "wss") or not address.hostname or address.username is not None
            or address.password is not None or address.path != "/stream" or address.query
            or address.fragment or any(ord(c) <= 32 or ord(c) > 126 for c in endpoint)):
        raise ValueError("endpoint must be ws[s]://host[:port]/stream without credentials or query")
    if address.port is not None and address.port == 0:
        raise ValueError("endpoint port must be 1..65535")
    identity_dir = Path(identity_dir)
    public = (identity_dir / "public.bin").read_bytes()
    pin = (identity_dir / "public.sha256").read_text(encoding="ascii").strip().lower()
    if len(public) != 800 or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("expected 800-byte ML-KEM-512 public key and 64-hex SHA-256 pin")
    if not hmac.compare_digest(hashlib.sha256(public).hexdigest(), pin):
        raise ValueError("public key SHA-256 does not match pin")
    if token is None:
        if address.scheme != "wss":
            raise ValueError("account pairing requires wss")
        return dict(version=2, endpoint=endpoint, public_key_hex=public.hex(), public_key_sha256=pin)
    if not 32 <= len(token) <= 256 or not all(33 <= ord(c) <= 126 for c in token):
        raise ValueError("invalid access token")
    return dict(version=1, endpoint=endpoint, token=token,
                public_key_hex=public.hex(), public_key_sha256=pin)


def export_config(identity_dir, endpoint, token_file, output_file):
    config = configuration(identity_dir, endpoint, read_token(token_file) if token_file else None)
    _new_file(Path(output_file), (json.dumps(config, indent=2) + "\n").encode("utf-8"), 0o600)
    return Path(output_file)


def prepare_pairing(identity_dir, endpoint, output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("output directory already exists; choose a new directory")
    token = secrets.token_urlsafe(32)
    config = configuration(identity_dir, endpoint, token)
    public = bytes.fromhex(config['public_key_hex'])
    pin = config['public_key_sha256']
    output_dir.mkdir(parents=True, mode=0o700)
    public_dir = output_dir / "public"
    public_dir.mkdir(mode=0o755)
    _new_file(public_dir / "public.bin", public, 0o644)
    _new_file(public_dir / "public.sha256", (pin + "\n").encode("ascii"), 0o644)
    _new_file(output_dir / "relay.token", (token + "\n").encode("ascii"), 0o600)
    pairing = f"endpoint={endpoint}\ntoken={token}\npin={pin}\n"
    _new_file(output_dir / "pairing.txt", pairing.encode("ascii"), 0o600)
    _new_file(output_dir / "pairing.json", (json.dumps(config, indent=2) + "\n").encode("utf-8"), 0o600)
    return output_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-dir", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    outputs = parser.add_mutually_exclusive_group(required=True)
    outputs.add_argument("--output-dir", type=Path)
    outputs.add_argument("--config-file", type=Path, help="Export schema2 WSS JSON; --token-file explicitly exports development schema1")
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    if args.config_file:
        print(export_config(args.identity_dir, args.endpoint, args.token_file, args.config_file).resolve())
        return
    if args.token_file:
        parser.error('--token-file is only used with --config-file')
    output = prepare_pairing(args.identity_dir, args.endpoint, args.output_dir)
    for path in (output / "public", output / "relay.token", output / "pairing.txt"):
        print(path.resolve())


if __name__ == "__main__":
    main()
