"""Verify/export a development board identity; optionally boot/provision via JTAG.

Never opens CDC, initiates a HostSession, or sends START. The Windows PC used
for JTAG provisioning remains trusted and can access the development private key.
"""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pc/src/host"))
from build_manifest import verify
from g6_board import jtag
from handshake import wipe_secret
from m09 import OUT, PK, SK, load_test_public_key
from transient_file import read_mutable_file


def prepare(workspace, identity_output, tool_root, provision=False):
    workspace = Path(workspace).resolve()
    identity_output = Path(identity_output).resolve()
    if identity_output.exists():
        raise FileExistsError("Use a fresh identity output directory")
    if identity_output.is_relative_to(OUT.resolve()):
        raise ValueError("Public export must be separate from the private key directory")
    manifest, checked = verify(workspace, "g6_usb_manifest.json")
    if (manifest.get("application") != "g6_usb" or
            not manifest.get("development_provisioning_required") or
            manifest.get("security_profile") not in
            ("development_jtag_mailbox", "development_jtag_mailbox_secure_cleanup")):
        raise ValueError("Expected a verified development JTAG G6 build")
    pk = load_test_public_key(OUT)
    if len(pk) != PK:
        raise ValueError("Expected an 800-byte ML-KEM-512 public key")
    pin = hashlib.sha256(pk).hexdigest()
    if provision:
        sk = read_mutable_file(OUT / "private.bin", SK)
        try:
            if len(sk) != SK or not hmac.compare_digest(sk[768:1568], pk):
                raise ValueError("Development private/public key mismatch")
            jtag(workspace, pk, sk, Path(tool_root).resolve())
        finally:
            wipe_secret(sk)
    # Export only public material, and only after requested provisioning succeeds.
    identity_output.mkdir(parents=True)
    (identity_output / "public.bin").write_bytes(pk)
    (identity_output / "public.sha256").write_text(pin + "\n", encoding="ascii")
    identity = dict(protocol_version=1, suite=1, public_key_hex=pk.hex(),
                    public_key_sha256=pin, security_profile=manifest["security_profile"],
                    jtag_provisioned=provision, authenticated_video_verified=False)
    (identity_output / "board_identity.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return dict(identity_output=str(identity_output), checked_files=checked,
                public_key_sha256=pin, jtag_provisioned=provision,
                authenticated_video_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--identity-output", type=Path, required=True)
    parser.add_argument("--tool-root", type=Path, default=Path("D:/AmdDesignTools/2026.1"))
    parser.add_argument("--provision", action="store_true",
                        help="Boot and provision volatile board DDR via JTAG; no USB handshake")
    args = parser.parse_args()
    print(json.dumps(prepare(args.workspace, args.identity_output,
                             args.tool_root, args.provision), indent=2))


if __name__ == "__main__":
    main()
