"""Generate public-only bundles; explicitly validate installed Linux sshd on request."""

import argparse
import base64
import binascii
import hashlib
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys

USER = "eyepqc-tunnel"
INSTALL = Path("/etc/eyepqc-tunnel")
KEY_OPTIONS = 'restrict,port-forwarding,permitlisten="0.0.0.0:8765" '
SERVICE = Path(__file__).with_name("eyepqc-tunnel.service")


def safe_path(value):
    path = Path(value)
    if not path.is_absolute() or any(p in {".", ".."} for p in str(value).replace("\\", "/").split("/")):
        raise ValueError("use an absolute path without dot components")
    if any(p.lower() in {".ssh", ".git", "private", "windows"} for p in path.parts):
        raise ValueError("protected path")
    for parent in (path, *path.parents):
        if parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction()):
            raise ValueError("symlinks and junctions are not allowed")
    if path == Path(path.anchor):
        raise ValueError("filesystem root is not allowed")
    if os.name != "nt" and path.parts[1] in {"etc", "usr", "bin", "sbin", "run", "var", "root", "proc", "dev", "sys"}:
        raise ValueError("generate into a staging directory, not a system directory")
    return path


def public_key(text):
    # Accept one plain Ed25519 public key, never authorized_keys options or private PEM.
    lines = text.strip().splitlines()
    if len(lines) != 1 or len(text) > 1024 or any(ord(c) < 32 and c not in "\r\n\t" for c in text):
        raise ValueError("expected one Ed25519 public key")
    fields = lines[0].split()
    if len(fields) < 2 or fields[0] != "ssh-ed25519":
        raise ValueError("only plain ssh-ed25519 public keys are accepted")
    try:
        wire = base64.b64decode(fields[1], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid public key base64") from exc
    prefix = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32)
    if len(wire) != len(prefix) + 32 or not wire.startswith(prefix) or wire[-32:] == bytes(32):
        raise ValueError("invalid Ed25519 SSH wire key")
    if base64.b64encode(wire).decode("ascii") != fields[1]:
        raise ValueError("non-canonical public key base64")
    return " ".join(fields[:2])


def config(ssh_port=22022, user=USER):
    if user != USER:
        raise ValueError("only the dedicated eyepqc-tunnel user is allowed")
    if type(ssh_port) is not int or not 1024 <= ssh_port <= 65535 or ssh_port == 8765:
        raise ValueError("SSH port must be 1024..65535 and differ from TCP8765")
    return f"""# Independent daemon: never include /etc/ssh/sshd_config.
Port {ssh_port}
ListenAddress 0.0.0.0
AddressFamily inet
HostKey /etc/eyepqc-tunnel/ssh_host_ed25519_key
PidFile /run/eyepqc-tunnel/sshd.pid
AllowUsers {user}
PermitRootLogin no
AuthenticationMethods publickey
PubkeyAuthentication yes
PubkeyAcceptedAlgorithms ssh-ed25519
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitEmptyPasswords no
HostbasedAuthentication no
GSSAPIAuthentication no
UsePAM no
StrictModes yes
AuthorizedKeysFile /etc/eyepqc-tunnel/authorized_keys
AuthorizedKeysCommand none
TrustedUserCAKeys none
AllowTcpForwarding remote
GatewayPorts clientspecified
PermitListen 0.0.0.0:8765
PermitOpen none
AllowStreamLocalForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTTY no
PermitTunnel no
PermitUserRC no
PermitUserEnvironment no
MaxSessions 0
ForceCommand /bin/false
LoginGraceTime 30
MaxAuthTries 3
MaxStartups 3:30:6
ClientAliveInterval 15
ClientAliveCountMax 3
LogLevel VERBOSE
"""


def fingerprint(key):
    digest = hashlib.sha256(base64.b64decode(key.split()[1], validate=True)).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


def generate(key_file, output_dir, expected_fingerprint, ssh_port=22022):
    rendered = config(ssh_port)
    key_path = safe_path(key_file)
    output = safe_path(output_dir)
    if key_path.suffix != ".pub" or not key_path.is_file() or key_path.stat().st_size > 1024:
        raise ValueError("input must be a small regular .pub file")
    key = public_key(key_path.read_text(encoding="ascii"))
    if expected_fingerprint != fingerprint(key):
        raise ValueError("public key does not match independently verified dedicated-key SHA256 fingerprint")
    files = {"sshd_config": rendered, "authorized_keys": KEY_OPTIONS + key + "\n",
             "eyepqc-tunnel.service": SERVICE.read_text(encoding="ascii")}
    output.mkdir(mode=0o700)  # Exclusive: no overwrites and no implicit parent creation.
    created = []
    try:
        for name, content in files.items():
            with (output / name).open("x", encoding="ascii", newline="\n") as handle:
                created.append(output / name)
                if os.name != "nt":
                    os.fchmod(handle.fileno(), 0o600)
                handle.write(content)
    except Exception:
        for path in created:
            path.unlink()
        output.rmdir()
        raise
    return output


def validate_bundle(directory):
    directory = safe_path(directory)
    expected_names = {"sshd_config", "authorized_keys", "eyepqc-tunnel.service"}
    if not directory.is_dir() or {p.name for p in directory.iterdir()} != expected_names:
        raise ValueError("bundle must contain exactly the three generated files")
    for name in expected_names:
        path = safe_path(directory / name)
        if not path.is_file() or path.stat().st_size > 8192:
            raise ValueError("invalid bundle file")
    cfg = (directory / "sshd_config").read_text(encoding="ascii")
    try:
        port = int(cfg.splitlines()[1].removeprefix("Port "))
    except (ValueError, IndexError) as exc:
        raise ValueError("invalid SSH port") from exc
    if cfg != config(port):
        raise ValueError("sshd configuration differs from frozen restrictions")
    auth = (directory / "authorized_keys").read_text(encoding="ascii")
    if not auth.startswith(KEY_OPTIONS) or auth != KEY_OPTIONS + public_key(auth[len(KEY_OPTIONS):]) + "\n":
        raise ValueError("authorized_keys must contain exactly the restricted dedicated key")
    if (directory / "eyepqc-tunnel.service").read_text(encoding="ascii") != SERVICE.read_text(encoding="ascii"):
        raise ValueError("service differs from template")
    return cfg, auth


def validate_linux(directory):
    cfg, auth = validate_bundle(directory)
    if sys.platform != "linux":
        raise RuntimeError("Linux sshd validation NOT EXECUTED: requires a Linux host")
    import pwd
    import grp
    if os.geteuid() != 0:
        raise RuntimeError("Linux installed-files validation requires root")
    account = pwd.getpwnam(USER)
    if account.pw_uid == 0 or account.pw_gid == 0 or account.pw_dir != "/nonexistent" or account.pw_shell not in {"/usr/sbin/nologin", "/sbin/nologin", "/bin/false"}:
        raise ValueError("dedicated user must be non-root with /nonexistent home and a disabled shell")
    if grp.getgrgid(account.pw_gid).gr_name != USER or set(os.getgrouplist(USER, account.pw_gid)) != {account.pw_gid}:
        raise ValueError("dedicated user must have only its dedicated primary group")
    shadow = subprocess.run(["/usr/bin/getent", "shadow", USER], capture_output=True,
                            text=True, timeout=15, check=True).stdout.strip().split(":")
    if len(shadow) != 9 or shadow[0] != USER or shadow[1] != "*":
        raise ValueError("dedicated account requires an unusable '*' password, not a locked '!' account")
    checks = {Path("/etc"): 0o755, INSTALL: 0o755,
              INSTALL / "sshd_config": 0o600, INSTALL / "authorized_keys": 0o644,
              INSTALL / "ssh_host_ed25519_key": 0o600,
              Path("/etc/systemd/system/eyepqc-tunnel.service"): 0o644}
    for path, mode in checks.items():
        for parent in (path, *path.parents):
            if parent.is_symlink():
                raise ValueError("installed paths must not use symlinks")
            parent_metadata = parent.stat()
            if parent_metadata.st_uid != 0 or parent_metadata.st_gid != 0 or parent_metadata.st_mode & 0o022:
                raise ValueError("installed paths and parents must be root-owned and not group/world writable")
        metadata = path.stat()
        if metadata.st_uid != 0 or metadata.st_gid != 0 or stat.S_IMODE(metadata.st_mode) != mode:
            raise ValueError(f"expected root:root mode {mode:o}: {path}")
        if path in {Path("/etc"), INSTALL}:
            if not stat.S_ISDIR(metadata.st_mode):
                raise ValueError("expected installed directory")
        elif not stat.S_ISREG(metadata.st_mode):
            raise ValueError("expected regular installed file")
    expected = {"sshd_config": cfg, "authorized_keys": auth}
    for name, content in expected.items():
        if (INSTALL / name).read_text(encoding="ascii") != content:
            raise ValueError(f"installed {name} differs from validated bundle")
    if Path("/etc/systemd/system/eyepqc-tunnel.service").read_text(encoding="ascii") != SERVICE.read_text(encoding="ascii"):
        raise ValueError("installed service differs from template")
    daemon = Path("/usr/sbin/sshd")
    if not daemon.is_file():
        raise RuntimeError("Linux sshd validation NOT EXECUTED: /usr/sbin/sshd missing")
    daemon_metadata = daemon.stat()
    if daemon.is_symlink() or daemon_metadata.st_uid != 0 or daemon_metadata.st_mode & 0o022:
        raise ValueError("sshd executable must be a root-owned regular non-writable system binary")
    for args in ([str(daemon), "-t", "-f", str(INSTALL / "sshd_config")],
                 [str(daemon), "-T", "-f", str(INSTALL / "sshd_config"), "-C", f"user={USER},host=localhost,addr=127.0.0.1"]):
        result = subprocess.run(args, capture_output=True, text=True, timeout=15, check=True)
    validate_effective(cfg, result.stdout)


def validate_effective(cfg, stdout):
    effective = {}
    for line in stdout.splitlines():
        if " " not in line:
            continue
        name, value = line.split(" ", 1)
        name = name.lower()
        if name in effective:
            raise ValueError(f"duplicate effective sshd directive: {name}")
        effective[name] = value
    for line in cfg.splitlines():
        if not line or line.startswith("#"):
            continue
        name, value = line.split(" ", 1)
        # sshd canonicalizes ListenAddress to include its port.
        if name == "ListenAddress":
            value += ":" + effective.get("port", "")
        if effective.get(name.lower()) != value:
            raise ValueError(f"effective sshd restriction differs: {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("generate")
    create.add_argument("--public-key-file", required=True)
    create.add_argument("--output-dir", required=True)
    create.add_argument("--expected-key-sha256", required=True)
    create.add_argument("--ssh-port", type=int, default=22022)
    verify = commands.add_parser("validate")
    verify.add_argument("--bundle-dir", required=True)
    verify.add_argument("--linux-sshd-check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            generate(args.public_key_file, args.output_dir, args.expected_key_sha256, args.ssh_port)
            print("Public-only bundle generated; Linux sshd/public-network acceptance NOT EXECUTED.")
        elif args.linux_sshd_check:
            validate_linux(args.bundle_dir)
            print("Installed Linux sshd -t/-T passed; service/tunnel/public-network acceptance NOT EXECUTED.")
        else:
            validate_bundle(args.bundle_dir)
            print("Static bundle validation passed; Linux sshd/public-network acceptance NOT EXECUTED.")
    except (ValueError, OSError, RuntimeError, KeyError, UnicodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
