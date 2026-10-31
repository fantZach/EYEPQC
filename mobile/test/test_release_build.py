"""Offline Gradle trust/signing boundary checks; temporary CA fixtures are not deployment identities."""
import datetime
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'build/mobile_toolchain'
JAVAC = shutil.which('javac')
JDK = Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else Path(JAVAC).resolve().parent.parent if JAVAC else None
SIGNING = ('EYEPQC_ANDROID_KEYSTORE', 'EYEPQC_ANDROID_KEY_ALIAS', 'EYEPQC_ANDROID_STORE_PASSWORD', 'EYEPQC_ANDROID_KEY_PASSWORD')


class ReleaseBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if JDK is None or not (JDK/'bin/javac.exe').is_file():
            raise unittest.SkipTest('Set JAVA_HOME to a JDK 17+ installation; release integration checks were not executed.')
        if not (TOOLS/'sdk/platforms/android-35/android.jar').is_file() or not (TOOLS/'gradle-8.9/bin/gradle.bat').is_file():
            raise unittest.SkipTest('Prepare the documented local Android SDK/Gradle cache; release integration checks were not executed.')
        cls.temp = tempfile.TemporaryDirectory(prefix='eyepqc-release-fixture-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.folder = Path(cls.temp.name)
        cls.env = dict(os.environ, JAVA_HOME=str(JDK), ANDROID_HOME=str(TOOLS / 'sdk'), GRADLE_USER_HOME=str(TOOLS / 'gradle-user'))
        for name in SIGNING:
            cls.env.pop(name, None)
        cls.ca = cls.folder / 'fixture-ca.pem'
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'EYEPQC offline fixture only')])
        now = datetime.datetime.now(datetime.timezone.utc)
        for label, ca, expiry in [('valid', True, 1), ('leaf', False, 1), ('expired', True, -1)]:
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(days=2))
                    .not_valid_after(now+datetime.timedelta(days=expiry))
                    .add_extension(x509.BasicConstraints(ca=ca, path_length=None), True).sign(key, hashes.SHA256()))
            path = cls.ca if label == 'valid' else cls.folder / (label+'.pem')
            path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (cls.folder / 'private.pem').write_bytes(cls.ca.read_bytes()+b'-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----\n')
        (cls.folder / 'multiple.pem').write_bytes(cls.ca.read_bytes()*2)

    def gradle(self, task=':app:help', ca=None, extra_env=None):
        command = [str(TOOLS / 'gradle-8.9/bin/gradle.bat'), '--no-daemon', '--offline', '-p', str(ROOT / 'mobile')]
        init = ROOT / 'tmp/json_mobile_init.gradle'
        if init.is_file():
            command += ['--init-script', str(init)]
        if ca:
            command.append('-PeyepqcTrustCaFile='+str(ca))
        return subprocess.run(command+[task], env={**self.env, **(extra_env or {})}, capture_output=True, text=True, timeout=180)

    def test_01_reject_invalid_ca_and_partial_signing(self):
        for path in (self.folder/'private.pem', self.folder/'multiple.pem', self.folder/'leaf.pem', self.folder/'expired.pem'):
            with self.subTest(ca=path.name):
                result = self.gradle(ca=path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Deployment CA', result.stdout+result.stderr)
        result = self.gradle(extra_env={'EYEPQC_ANDROID_STORE_PASSWORD': 'fixture-secret-not-real'})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('fixture-secret-not-real', result.stdout+result.stderr)
        self.assertIn('all four', result.stdout+result.stderr)

    def test_02_explicit_ca_then_system_only_has_no_stale_ca(self):
        from check_debug_ca import check
        aapt = TOOLS / 'sdk/build-tools/35.0.0/aapt.exe'
        result = self.gradle(':app:assembleRelease', self.ca)
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr)[-4000:])
        result = self.gradle(':app:assembleDebug', self.ca)
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr)[-4000:])
        check(ROOT, aapt, self.ca)
        result = self.gradle(':app:assembleRelease')
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr)[-4000:])
        result = self.gradle(':app:assembleDebug')
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr)[-4000:])
        check(ROOT, aapt)

    def test_03_external_signing_and_required_signing_guard(self):
        shell = shutil.which('pwsh') or 'powershell.exe'
        command = [shell, '-NoProfile', '-File', str(ROOT/'mobile/build.ps1'), '-Jdk', str(JDK),
                   '-Sdk', str(TOOLS/'sdk'), '-Gradle', str(TOOLS/'gradle-8.9/bin/gradle.bat'), '-Variant', 'Release', '-Offline', '-RequireSigned']
        init = ROOT/'tmp/json_mobile_init.gradle'
        if init.is_file():
            command += ['-InitScript', str(init)]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('signing material is missing', result.stdout+result.stderr)
        store = self.folder/'fixture-release.p12'
        env = {**self.env, **dict(zip(SIGNING, [str(store), 'fixture', 'fixture-only-password', 'fixture-only-password']))}
        created = subprocess.run([str(JDK/'bin/keytool.exe'), '-genkeypair', '-alias', 'fixture', '-keyalg', 'RSA',
                                  '-keysize', '2048', '-validity', '1', '-dname', 'CN=EYEPQC Offline Fixture',
                                  '-storetype', 'PKCS12', '-keystore', str(store),
                                  '-storepass:env', SIGNING[2], '-keypass:env', SIGNING[3]], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(created.returncode, 0)
        output = self.folder/'signed-output'
        result = subprocess.run(command+['-OutputDirectory', str(output)], env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr)[-3000:])
        self.assertNotIn('fixture-only-password', result.stdout+result.stderr)
        import json
        manifest = json.loads((output/'manifest.json').read_text())
        self.assertEqual(manifest['signing'], 'external-release-key')
        self.assertEqual(manifest['user_acceptance'], 'pending')
        self.assertEqual(len(manifest['signer_sha256']), 64)
        result = subprocess.run(command+['-OutputDirectory', str(output)], env=env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no overwrite', result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
