"""Windows launcher checks with synthetic TCP state; no USB or service mutation."""

import os
from pathlib import Path
import subprocess
import unittest


@unittest.skipUnless(os.name == "nt", "Windows PowerShell launcher")
class LauncherTests(unittest.TestCase):
    def run_script(self, prefix, arguments):
        path = Path(__file__).resolve().parents[1] / "run_relay.ps1"
        command = prefix + f"; & '{str(path).replace(chr(39), chr(39) * 2)}' {arguments}"
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                              capture_output=True, text=True, timeout=15)

    def test_run_refuses_existing_listener_before_reading_token(self):
        result = self.run_script(
            "function Get-NetTCPConnection { [pscustomobject]@{LocalPort=8765; State='Listen'; OwningProcess=12345} }",
            "-Mode Run -TokenFile 'does-not-exist.token'")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already has a listener", result.stderr)
        self.assertIn("12345", result.stderr)
        self.assertNotIn("Resolve-Path", result.stderr)

    def test_status_needs_no_token_or_serial_device(self):
        result = self.run_script("function Get-NetTCPConnection { }",
                                 "-Mode Status -TokenFile 'does-not-exist.token'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("No relay/download TCP endpoints", result.stdout)
        self.assertIn("do not prove", result.stdout)

    def test_automatic_pairing_refuses_token_mode_before_reading_files(self):
        result = self.run_script("function Get-NetTCPConnection { }",
                                 "-Mode Run -PairingFile 'does-not-exist.json'")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PairingFile requires AccountsFile and TLS", result.stderr)
        self.assertNotIn("Resolve-Path", result.stderr)


if __name__ == "__main__":
    unittest.main()
