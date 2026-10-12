"""No hardware access: verify public export and provision-only boundaries."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prepare_mobile", ROOT / "board/prj/prepare_mobile.py")
prepare_mobile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_mobile)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.keys = self.directory / "keys"
        self.keys.mkdir()
        self.pk = bytes(i % 256 for i in range(800))
        self.sk = bytearray(1632)
        self.sk[768:1568] = self.pk
        (self.keys / "public.bin").write_bytes(self.pk)
        (self.keys / "public.sha256").write_text(hashlib.sha256(self.pk).hexdigest())
        (self.keys / "private.bin").write_bytes(self.sk)
        self.manifest = dict(application="g6_usb", development_provisioning_required=True,
                             security_profile="development_jtag_mailbox")
        self.addCleanup(patch.stopall)
        patch.object(prepare_mobile, "OUT", self.keys).start()
        self.verifier = patch.object(prepare_mobile, "verify", return_value=(self.manifest, 12)).start()
        self.jtag = patch.object(prepare_mobile, "jtag").start()

    def call(self, provision=False):
        return prepare_mobile.prepare(self.directory / "workspace", self.directory / "public",
                                      self.directory / "tools", provision)

    def test_default_exports_only_public_material_and_never_jtag(self):
        result = self.call()
        self.jtag.assert_not_called()
        self.assertFalse(result["jtag_provisioned"])
        files = {p.name for p in (self.directory / "public").iterdir()}
        self.assertEqual(files, {"public.bin", "public.sha256", "board_identity.json"})
        identity = json.loads((self.directory / "public/board_identity.json").read_text())
        self.assertEqual(bytes.fromhex(identity["public_key_hex"]), self.pk)
        self.assertFalse(identity["authenticated_video_verified"])

    def test_provision_only_and_private_buffer_wiped(self):
        self.assertTrue(self.call(True)["jtag_provisioned"])
        self.jtag.assert_called_once()
        self.assertEqual(self.jtag.call_args.args[2], bytearray(1632))

    def test_failure_wipes_private_and_exports_nothing(self):
        self.jtag.side_effect = RuntimeError("injected boot failure")
        with self.assertRaises(RuntimeError):
            self.call(True)
        self.assertEqual(self.jtag.call_args.args[2], bytearray(1632))
        self.assertFalse((self.directory / "public").exists())

    def test_rejects_production_profile_before_jtag(self):
        self.manifest["security_profile"] = "external_provider_unvalidated"
        with self.assertRaises(ValueError):
            self.call(True)
        self.jtag.assert_not_called()

    def test_rejects_mismatched_private_before_jtag(self):
        (self.keys / "private.bin").write_bytes(bytes(1632))
        with self.assertRaises(ValueError):
            self.call(True)
        self.jtag.assert_not_called()

    def test_rejects_overwrite_and_private_directory_export(self):
        self.call()
        with self.assertRaises(FileExistsError):
            self.call(True)
        with self.assertRaises(ValueError):
            prepare_mobile.prepare(self.directory / "workspace", self.keys / "export",
                                   self.directory / "tools")


if __name__ == "__main__":
    unittest.main()
