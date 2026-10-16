"""Opt-in real setup/uninstall, restricted to an independently compiled fixture."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

import test_install_data


@unittest.skipUnless(os.environ.get('EYEPQC_INSTALLER_FIXTURE_ROOT'), 'explicit isolated fixture only')
class InstallerLifecycleTests(unittest.TestCase):
    def test_install_upgrade_uninstall_preserve_runtime_materials(self):
        root = Path(os.environ['EYEPQC_INSTALLER_FIXTURE_ROOT']).resolve()
        repo = Path(__file__).resolve().parents[2]
        self.assertTrue(root.is_relative_to(repo / 'build/pc_installer') or
                        root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertGreater(len(root.parts), len(Path(tempfile.gettempdir()).parts))
        setup = repo / 'build/pc_installer/dist/EYEPQC-Setup-1.3.1-fixture.exe'
        self.assertTrue(setup.is_file())
        app = root / 'bin'
        self.assertFalse((app / 'eyepqc.exe').exists(), 'use a fresh fixture root')
        user = root / 'user'
        self.assertFalse(user.exists(), 'do not mutate an existing fixture or user settings')
        import winreg
        fixture_environment = r'Software\EYEPQC\InstallerFixture\Environment'
        fixture_ownership = r'Software\EYEPQC\InstallerFixture\PathOwnership'
        def query(key_name, value_name):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_name) as handle:
                    return winreg.QueryValueEx(handle, value_name)
            except FileNotFoundError:
                return None
        actual_path = query('Environment', 'Path')
        self.assertIsNone(query(fixture_environment, 'Path'), 'use a clean fixture registry branch')
        self.assertIsNone(query(fixture_ownership, 'Entry'), 'do not replace another fixture owner')
        key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{BC45B197-2603-498A-B857-C58A97E11DC0}_is1'
        def registered():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
                    return True
            except FileNotFoundError:
                return False
        self.assertFalse(registered(), 'do not replace an existing fixture installation')
        test_install_data.InstallDataTests.setUpClass()
        fixture = test_install_data.InstallDataTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        env = dict(os.environ, LOCALAPPDATA=str(user))
        def execute(arguments, timeout=120):
            result = subprocess.run(arguments, env=env, capture_output=True, text=True, timeout=timeout)
            self.assertEqual(result.returncode, 0, 'fixture process failed; inspect its isolated setup log')
            return result
        args = [str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
                '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/DIR=' + str(app)]
        root.mkdir(parents=True, exist_ok=True)
        execute([*args, '/SOURCECONFIG=' + str(fixture.config), '/LOG=' + str(root / 'install.log')])
        self.assertEqual(query(fixture_environment, 'Path'), (str(app), winreg.REG_SZ))
        self.assertEqual(query(fixture_ownership, 'Entry')[0], str(app))
        self.assertTrue((app / 'eyepqc.exe').is_file())
        self.assertTrue(registered())
        shown = json.loads(execute([str(app / 'eyepqc.exe'), 'config', 'show']).stdout)
        settings = Path(shown['settings_file'])
        self.assertEqual(settings, user / 'EYEPQC/pc/settings.json')
        data = settings.parent / 'data'
        self.assertEqual(sum(path.is_file() for path in data.rglob('*')), 6)
        execute([str(app / 'eyepqc.exe'), 'check'])
        account = data / 'private/accounts.json'
        account.write_text(json.dumps({'maintained': {'salt': '01' * 16, 'hash': '02' * 32}}))
        before = {path: path.read_bytes() for path in data.rglob('*') if path.is_file()}
        saved_settings = settings.read_bytes()
        execute([*args, '/LOG=' + str(root / 'upgrade.log')])
        self.assertEqual(query(fixture_environment, 'Path'), (str(app), winreg.REG_SZ))
        self.assertTrue(all(path.read_bytes() == content for path, content in before.items()))
        self.assertEqual(settings.read_bytes(), saved_settings)
        execute([str(app / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'])
        for _ in range(100):
            if not (app / 'eyepqc.exe').exists() and not registered():
                break
            time.sleep(0.1)
        self.assertFalse((app / 'eyepqc.exe').exists())
        self.assertFalse(registered())
        self.assertEqual(settings.read_bytes(), saved_settings)
        self.assertTrue(all(path.read_bytes() == content for path, content in before.items()))
        self.assertIsNone(query(fixture_environment, 'Path'))
        self.assertIsNone(query(fixture_ownership, 'Entry'))
        self.assertEqual(query('Environment', 'Path'), actual_path, 'fixture must not touch actual user PATH')
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, fixture_environment)
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r'Software\EYEPQC\InstallerFixture')
        except FileNotFoundError:
            pass

    def test_path_preserves_type_existing_entries_and_external_edits(self):
        import winreg
        root = Path(os.environ['EYEPQC_INSTALLER_FIXTURE_ROOT']).resolve()
        repo = Path(__file__).resolve().parents[2]
        self.assertTrue(root.is_relative_to(repo / 'build/pc_installer') or
                        root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertGreater(len(root.parts), len(Path(tempfile.gettempdir()).parts))
        setup = repo / 'build/pc_installer/dist/EYEPQC-Setup-1.3.1-fixture.exe'
        environment = r'Software\EYEPQC\InstallerFixture\Environment'
        ownership = r'Software\EYEPQC\InstallerFixture\PathOwnership'
        uninstall_key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{BC45B197-2603-498A-B857-C58A97E11DC0}_is1'
        def query(key, name):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
                    return winreg.QueryValueEx(handle, name)
            except FileNotFoundError:
                return None
        def write(value, kind=winreg.REG_SZ):
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, environment) as handle:
                winreg.SetValueEx(handle, 'Path', 0, kind, value)
        self.assertIsNone(query(environment, 'Path'), 'fixture registry already in use')
        self.assertIsNone(query(ownership, 'Entry'), 'fixture registry already owned')
        self.assertIsNone(query(uninstall_key, 'DisplayName'), 'fixture installation already in use')
        actual_path = query('Environment', 'Path')
        test_install_data.InstallDataTests.setUpClass()
        source = test_install_data.InstallDataTests()
        source.setUp()
        self.addCleanup(source.doCleanups)
        cases = ('empty', 'plain', 'expandable', 'preexisting', 'environment_variable', 'external_append',
                 'external_entry_change', 'external_duplicate', 'wrong_type')
        for name in cases:
            with self.subTest(name=name):
                case = root / name
                app = case / 'bin'
                self.assertFalse(app.exists(), 'use fresh fixture directories')
                env = dict(os.environ, LOCALAPPDATA=str(case / 'user'), EYEPQC_PATH_FIXTURE=str(app))
                case.mkdir(parents=True)
                original = r'%SystemRoot%\fixture;;C:\keep;'
                kind = winreg.REG_EXPAND_SZ if name == 'expandable' else winreg.REG_SZ
                if name == 'empty':
                    original = ''
                if name == 'plain':
                    original = r'C:\keep;;C:\other'
                if name == 'preexisting':
                    original += '  "' + str(app).upper() + '\\"  ;C:\\last'
                if name == 'environment_variable':
                    original += '%EYEPQC_PATH_FIXTURE%\\'
                    kind = winreg.REG_EXPAND_SZ
                if name == 'wrong_type':
                    original, kind = 123, winreg.REG_DWORD
                write(original, kind)
                arguments = [str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOICONS',
                    '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/DIR=' + str(app),
                    '/LOG=' + str(case / 'install.log')]
                result = subprocess.run([*arguments, '/SOURCECONFIG=' + str(source.config)],
                                        env=env, capture_output=True, timeout=120)
                if name == 'wrong_type':
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((app / 'eyepqc.exe').exists())
                    self.assertEqual(query(environment, 'Path'), (original, kind))
                    self.assertIsNone(query(ownership, 'Entry'))
                else:
                    self.assertEqual(result.returncode, 0, 'inspect isolated setup log')
                    preexisting = name in ('preexisting', 'environment_variable')
                    expected = original if preexisting else original + (
                        '' if not original or original.endswith(';') else ';') + str(app)
                    self.assertEqual(query(environment, 'Path'), (expected, kind))
                    self.assertEqual(query(ownership, 'Entry') is None, preexisting)
                    # Upgrade must neither duplicate nor adopt a pre-existing user entry.
                    result = subprocess.run(arguments, env=env, capture_output=True, timeout=120)
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(query(environment, 'Path'), (expected, kind))
                    restored = original
                    if name == 'external_append':
                        write('C:\\new-first;' + expected + ';C:\\new-last', kind)
                        restored = 'C:\\new-first;' + original + 'C:\\new-last'
                    if name == 'external_entry_change':
                        restored = expected[:-len(str(app))] + str(app).upper()
                        write(restored, kind)
                    if name == 'external_duplicate':
                        restored = expected + ';' + str(app)
                        write(restored, kind)
                    result = subprocess.run([str(app / 'unins000.exe'), '/VERYSILENT',
                        '/SUPPRESSMSGBOXES', '/NORESTART'], env=env, capture_output=True, timeout=120)
                    self.assertEqual(result.returncode, 0)
                    for _ in range(100):
                        if not (app / 'eyepqc.exe').exists() and query(uninstall_key, 'DisplayName') is None:
                            break
                        time.sleep(.1)
                    self.assertFalse((app / 'eyepqc.exe').exists())
                    self.assertEqual(query(environment, 'Path'), (restored, kind))
                    self.assertIsNone(query(ownership, 'Entry'))
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, environment, 0, winreg.KEY_SET_VALUE) as handle:
                    winreg.DeleteValue(handle, 'Path')
        self.assertEqual(query('Environment', 'Path'), actual_path)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, environment)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r'Software\EYEPQC\InstallerFixture')
