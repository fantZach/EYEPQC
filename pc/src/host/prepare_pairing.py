"""Prepare local Android pairing files without loading board private material."""

import argparse
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit


def _new_file(path, data, mode):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, "wb") as target:
        target.write(data)


def prepare_pairing(identity_dir, endpoint, output_dir):
    endpoint = str(endpoint)
    address = urlsplit(endpoint)
    if (address.scheme not in ("ws", "wss") or not address.hostname or address.username is not None
            or address.password is not None or address.path != "/stream" or address.query
            or address.fragment or any(ord(c) <= 32 or ord(c) > 126 for c in endpoint)):
        raise ValueError("endpoint must be ws[s]://host[:port]/stream without credentials or query")
    if address.port is not None and address.port == 0:
        raise ValueError("endpoint port must be 1..65535")
    identity_dir, output_dir = Path(identity_dir), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("output directory already exists; choose a new directory")
    public = (identity_dir / "public.bin").read_bytes()
    pin = (identity_dir / "public.sha256").read_text(encoding="ascii").strip().lower()
    if len(public) != 800 or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("expected 800-byte ML-KEM-512 public key and 64-hex SHA-256 pin")
    if not hmac.compare_digest(hashlib.sha256(public).hexdigest(), pin):
        raise ValueError("public key SHA-256 does not match pin")
    token = secrets.token_urlsafe(32)
    output_dir.mkdir(parents=True, mode=0o700)
    public_dir = output_dir / "public"
    public_dir.mkdir(mode=0o755)
    _new_file(public_dir / "public.bin", public, 0o644)
    _new_file(public_dir / "public.sha256", (pin + "\n").encode("ascii"), 0o644)
    _new_file(output_dir / "relay.token", (token + "\n").encode("ascii"), 0o600)
    pairing = f"endpoint={endpoint}\ntoken={token}\npin={pin}\n"
    _new_file(output_dir / "pairing.txt", pairing.encode("ascii"), 0o600)
    return output_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity-dir", type=Path, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = prepare_pairing(args.identity_dir, args.endpoint, args.output_dir)
    for path in (output / "public", output / "relay.token", output / "pairing.txt"):
        print(path.resolve())


if __name__ == "__main__":
    main()
