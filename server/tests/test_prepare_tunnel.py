import base64
import contextlib
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_tunnel as tunnel


class TunnelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        wire = struct.pack(">I", 11) + b"ssh-ed25519" + struct.pack(">I", 32) + bytes(range(32))
        self.key = "ssh-ed25519 " + base64.b64encode(wire).decode("ascii")
        self.key_file = self.root / "tunnel.pub"
        self.key_file.write_text(self.key + " dedicated PC\n", encoding="ascii")
        self.output = self.root / "bundle"

    def generate(self, port=2222):
        return tunnel.generate(self.key_file, self.output, tunnel.fingerprint(self.key), port)

    def test_generate_exact_public_only_bundle(self):
        self.generate()
        cfg, auth = tunnel.validate_bundle(self.output)
        self.assertEqual(cfg, tunnel.config())
        self.assertEqual(auth, tunnel.KEY_OPTIONS + self.key + "\n")
        self.assertNotIn("dedicated PC", auth)
        self.assertEqual(len(list(self.output.iterdir())), 3)
        service = (self.output / "eyepqc-tunnel.service").read_text()
        self.assertIn("sshd -t -f /etc/eyepqc-tunnel/sshd_config", service)
        self.assertIn("Restart=no", service)
        self.assertNotIn("/etc/ssh/", service)
        if os.name != "nt":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
            for path in self.output.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_contract_closes_other_auth_and_forwarding(self):
        lines = set(tunnel.config().splitlines())
        expected = {"Port 2222", "AllowUsers eyepqc-tunnel", "AuthenticationMethods publickey",
                    "AuthorizedKeysCommand none", "TrustedUserCAKeys none", "UsePAM no",
                    "PasswordAuthentication no", "KbdInteractiveAuthentication no",
                    "GatewayPorts clientspecified", "AllowTcpForwarding remote",
                    "PermitListen 0.0.0.0:8765", "PermitOpen none", "MaxSessions 0",
                    "ForceCommand /bin/false", "PermitTTY no", "AllowAgentForwarding no",
                    "AllowStreamLocalForwarding no", "X11Forwarding no", "PermitTunnel no",
                    "PermitUserRC no", "PermitUserEnvironment no", "PubkeyAcceptedAlgorithms ssh-ed25519"}
        self.assertTrue(expected <= lines)
        self.assertFalse(any(line.startswith(("Include ", "Match ")) for line in lines))

    def test_ssh_port_change_is_bounded_and_never_22_or_public_port(self):
        self.generate(4433)
        self.assertIn("Port 4433\n", tunnel.validate_bundle(self.output)[0])
        for port in (0, 22, 443, 1023, 8765, 65536, -1, True, "2222", 2222.0):
            with self.subTest(port=port), self.assertRaises(ValueError):
                tunnel.config(port)

    def test_user_is_frozen(self):
        for user in ("root", "admin", "daemon", "nobody", "eyepqc-tunnel\nPermitRootLogin yes", "../root"):
            with self.subTest(user=user), self.assertRaises(ValueError):
                tunnel.config(user=user)

    def test_public_key_rejects_private_keys_options_multiple_keys_and_bad_wire(self):
        for key in ("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n", "restrict " + self.key,
                    self.key + "\n" + self.key, "ssh-rsa AAAA", "ssh-ed25519 !!!",
                    "ssh-ed25519 " + base64.b64encode(b"ssh-ed25519").decode(),
                    self.key + "\x00", self.key + "x", self.key + " " + "x" * 1100):
            with self.subTest(key=key[:35]), self.assertRaises(ValueError):
                tunnel.public_key(key)

    def test_invalid_key_and_port_leave_no_output(self):
        self.key_file.write_text("ssh-ed25519 !!!")
        with self.assertRaises(ValueError):
            self.generate()
        self.assertFalse(self.output.exists())
        with self.assertRaises(ValueError):
            self.generate(22)
        self.assertFalse(self.output.exists())

    def test_key_input_must_be_pub_regular_file(self):
        other = self.root / "id_ed25519"
        other.write_text(self.key)
        with self.assertRaises(ValueError):
            tunnel.generate(other, self.output, tunnel.fingerprint(self.key))
        with self.assertRaises(ValueError):
            tunnel.generate(self.root / "absent.pub", self.output, tunnel.fingerprint(self.key))

    def test_wrong_dedicated_key_fingerprint_leaves_no_output(self):
        with self.assertRaises(ValueError):
            tunnel.generate(self.key_file, self.output, "SHA256:" + "A" * 43)
        self.assertFalse(self.output.exists())

    def test_effective_output_parser_is_fail_closed(self):
        # Synthetic -T text tests only; this does not execute or emulate a Linux daemon.
        cfg = tunnel.config()
        effective = "\n".join(line for line in cfg.splitlines() if not line.startswith("#"))
        effective = effective.replace("ListenAddress 0.0.0.0", "ListenAddress 0.0.0.0:2222")
        tunnel.validate_effective(cfg, effective)
        for value in (effective.replace("AllowTcpForwarding remote", "AllowTcpForwarding yes"),
                      effective.replace("UsePAM no", ""), effective + "\nPort 22"):
            with self.assertRaises(ValueError):
                tunnel.validate_effective(cfg, value)

    def test_existing_directory_is_preserved(self):
        self.output.mkdir()
        marker = self.output / "operator-file"
        marker.write_text("keep")
        with self.assertRaises(FileExistsError):
            self.generate()
        self.assertEqual(marker.read_text(), "keep")
        self.assertEqual([p.name for p in self.output.iterdir()], ["operator-file"])

    def test_reject_relative_traversal_and_protected_paths(self):
        for path in ("relative", str(self.root / ".." / "escape"), str(self.root / ".ssh" / "bundle"),
                     str(self.root / "private" / "bundle"), self.root.anchor):
            with self.subTest(path=path), self.assertRaises(ValueError):
                tunnel.safe_path(path)

    def test_reject_links_without_following_them(self):
        # Mock the platform link flag: Windows may not grant symlink creation privileges.
        with patch.object(Path, "is_symlink", return_value=True), self.assertRaises(ValueError):
            tunnel.safe_path(self.output)
        if hasattr(Path, "is_junction"):
            with patch.object(Path, "is_junction", return_value=True), self.assertRaises(ValueError):
                tunnel.safe_path(self.output)

    def test_security_config_mutations_are_rejected(self):
        self.generate()
        path = self.output / "sshd_config"
        baseline = path.read_text()
        for old, new in (("AllowTcpForwarding remote", "AllowTcpForwarding yes"),
                         ("GatewayPorts clientspecified", "GatewayPorts yes"),
                         ("PermitListen 0.0.0.0:8765", "PermitListen any"),
                         ("MaxSessions 0", "MaxSessions 10"),
                         ("AllowUsers eyepqc-tunnel", "AllowUsers root"),
                         ("AuthorizedKeysFile /etc/eyepqc-tunnel/authorized_keys", "AuthorizedKeysFile .ssh/authorized_keys"),
                         ("Port 2222", "Port 22")):
            with self.subTest(new=new):
                path.write_text(baseline.replace(old, new))
                with self.assertRaises(ValueError):
                    tunnel.validate_bundle(self.output)
        path.write_text(baseline + "Include /etc/ssh/sshd_config\n")
        with self.assertRaises(ValueError):
            tunnel.validate_bundle(self.output)

    def test_key_restrictions_and_additional_key_rejected(self):
        self.generate()
        path = self.output / "authorized_keys"
        baseline = path.read_text()
        for value in (self.key + "\n", baseline.replace("8765", "8766"), baseline + self.key + "\n"):
            path.write_text(value)
            with self.assertRaises(ValueError):
                tunnel.validate_bundle(self.output)

    def test_service_mutation_and_extra_bundle_file_rejected(self):
        self.generate()
        path = self.output / "eyepqc-tunnel.service"
        original = path.read_text()
        path.write_text(original.replace("Restart=no", "Restart=always"))
        with self.assertRaises(ValueError):
            tunnel.validate_bundle(self.output)
        path.write_text(original)
        (self.output / "unexpected").write_text("extra")
        with self.assertRaises(ValueError):
            tunnel.validate_bundle(self.output)

    def test_cli_distinguishes_static_check_from_linux_execution(self):
        self.generate()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(tunnel.main(["validate", "--bundle-dir", str(self.output)]), 0)
        self.assertIn("Linux sshd/public-network acceptance NOT EXECUTED", stdout.getvalue())
        with patch.object(sys, "platform", "win32"), contextlib.redirect_stderr(stderr):
            self.assertEqual(tunnel.main(["validate", "--bundle-dir", str(self.output), "--linux-sshd-check"]), 1)
        self.assertIn("Linux sshd validation NOT EXECUTED", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
