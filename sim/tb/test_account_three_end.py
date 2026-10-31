"""Java/OkHttp WSS account login -> ciphertext relay -> real C ephemeral KEM.

Synthetic camera/USB and public test credentials; not phone or board acceptance.
Run mobile/test.ps1 first. TLS uses an isolated trusted fixture CA, never trust-all.
"""
import asyncio
import ctypes as ct
import datetime
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import ssl
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'pc/src/host'), str(ROOT / 'sim/tb')]
from accounts import Accounts, create_account
from relay import Relay
from protocol import decode_control, encode_control, encode_usb_record, USB_CONTROL
import test_g6 as reference
from test_m10 import array, setup
from test_three_end import SimulatedCdc
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class Ephemeral(ct.Structure):
    _fields_ = [('private_key', ct.c_ubyte * 1632), ('offer', ct.c_ubyte * 876),
                ('active', ct.c_ubyte)]


class EphemeralBoard(reference.MemoryBoard):
    def __init__(self, lib, kem, pk, sk):
        super().__init__(lib, kem, pk, sk)
        self.ephemeral = Ephemeral()
        self.business = False
        self.offers = []

    def write(self, record):
        for channel, message in self.decoder.feed(record):
            assert channel == USB_CONTROL
            kind, body = decode_control(message)
            if int(kind) == 1:
                assert body[:4] == b'\x01\x01\x00\x02'
                self.lib.eye_ephemeral_wipe(ct.byref(self.ephemeral))
                assert self.lib.eye_session_init(ct.byref(self.session), array(reference.G6.pk)) == 0
                self.business = False
                self.hello = message
                self.ack = encode_control(2, body[:4] + secrets.token_bytes(32))
                self.pending.extend(encode_usb_record(1, self.ack))
            elif int(kind) == 3:
                shared = self.kem.decaps(self.sk, body)
                try:
                    assert self.lib.eye_session_begin(ct.byref(self.session), array(shared),
                                                      array(self.hello), array(self.ack), array(message)) == 0
                finally:
                    shared[:] = bytes(len(shared))
                self.finished()
            elif int(kind) == 5:
                assert self.lib.eye_session_verify_host_finished(ct.byref(self.session), array(message)) == 0
                if not self.business:
                    coins = array(secrets.token_bytes(64))
                    try:
                        assert self.lib.eye_ephemeral_offer(ct.byref(self.ephemeral), ct.byref(self.session), coins) == 0
                    finally:
                        ct.memset(coins, 0, len(coins))
                    assert not any(self.session.video_key)
                    self.offers.append(bytes(self.ephemeral.offer))
                    self.pending.extend(encode_usb_record(1, bytes(self.ephemeral.offer)))
            elif int(kind) == 11:
                assert self.lib.eye_ephemeral_complete(ct.byref(self.ephemeral), ct.byref(self.session),
                                                       array(message), len(message)) == 0
                assert not any(bytes(self.ephemeral))
                self.business = True
                self.finished()
            else:
                assert self.lib.eye_session_command(ct.byref(self.session), array(message)) == 0
                if int(kind) == 6:
                    assert self.business
                    self.video()
        return len(record)

    def finished(self):
        out = (ct.c_ubyte * 44)()
        assert self.lib.eye_session_board_finished(ct.byref(self.session), out) == 0
        self.pending.extend(encode_usb_record(1, bytes(out)))


class AccountThreeEnd(unittest.IsolatedAsyncioTestCase):
    tcp_passthrough = False

    async def test_wss_ephemeral_video_rekey_stop_and_reconnect(self):
        reference.G6.setUpClass()
        self.addCleanup(reference.G6.tearDownClass)
        java = Path(os.environ['JAVA_HOME']) / 'bin/java.exe' if os.environ.get('JAVA_HOME') else Path(shutil.which('java') or 'java')
        tools = ROOT / 'build/mobile_toolchain'
        classpath = os.pathsep.join(str(tools / name) for name in
            ('classes', 'bcprov.jar', 'okhttp.jar', 'okio.jar', 'kotlin.jar', 'gson.jar'))
        with tempfile.TemporaryDirectory(prefix='eyepqc-account-interop-') as directory:
            folder = Path(directory)
            library = folder / ('eph.dll' if os.name == 'nt' else 'eph.so')
            sources = ['board/src/ps/src/' + name for name in
                       ('session.c', 'protocol.c', 'ephemeral.c', 'm09_mlkem.c')]
            sources += ['board/src/third_party/tinycrypt/lib/source/' + name for name in ('sha256.c', 'utils.c')]
            subprocess.run([os.environ.get('CC', 'gcc'), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-shared', '-fPIC', '-I', str(ROOT/'board/src/ps/include'), '-I',
                            str(ROOT/'board/src/third_party'), '-I', str(ROOT/'board/src/third_party/mlkem'),
                            '-I', str(ROOT/'board/src/third_party/tinycrypt/lib/include'),
                            *[str(ROOT/name) for name in sources], '-o', str(library)], check=True)
            lib = ct.CDLL(str(library))
            setup(lib)
            lib.eye_ephemeral_offer.argtypes = [ct.c_void_p] * 3
            lib.eye_ephemeral_complete.argtypes = [ct.c_void_p] * 3 + [ct.c_size_t]
            lib.eye_ephemeral_wipe.argtypes = [ct.c_void_p]
            try:
                key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
                name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
                now = datetime.datetime.now(datetime.timezone.utc)
                cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
                        .not_valid_after(now+datetime.timedelta(days=1))
                        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                        .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost')]), False)
                        .sign(key, hashes.SHA256()))
                certificate = folder/'ca.pem'
                certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                private = folder/'tls.key'
                private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
                trust = folder/'trust.p12'
                subprocess.run([str(java.with_name('keytool.exe')), '-importcert', '-noprompt', '-alias', 'fixture',
                                '-file', str(certificate), '-keystore', str(trust), '-storetype', 'PKCS12',
                                '-storepass', 'public-fixture-password'], check=True, capture_output=True)
                tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                tls.load_cert_chain(certificate, private)
                account_file = folder/'accounts.json'
                create_account(account_file, 'fixture-user', 'public-fixture-password')
                devices = []
                def factory():
                    device = SimulatedCdc.__new__(SimulatedCdc)
                    device.board = EphemeralBoard(lib, reference.G6.kem, reference.G6.pk, reference.G6.sk)
                    device.commands, device.closed, device._dtr = [], False, False
                    devices.append(device)
                    return device
                relay = Relay(accounts=Accounts(account_file), serial_factory=factory, queue_records=128)
                server = await relay.start('127.0.0.1', 0, tls=tls)
                port = server.sockets[0].getsockname()[1]
                tunnel = None
                if self.tcp_passthrough:
                    from test_cloud_passthrough import TcpPassthrough
                    tunnel = TcpPassthrough(port)
                    await tunnel.start()
                    port = tunnel.port
                public = folder/'public.bin'
                public.write_bytes(reference.G6.pk)
                import io
                from PIL import Image
                image = io.BytesIO()
                Image.new('RGB', (640,480), (0,120,180)).save(image, format='JPEG')
                expected = hashlib.sha256(image.getvalue()).hexdigest()
                try:
                    for mode in ('normal', 'rekey', 'timer', 'stop', 'normal'):
                        process = await asyncio.create_subprocess_exec(str(java),
                            '-Djavax.net.ssl.trustStore='+str(trust),
                            '-Djavax.net.ssl.trustStorePassword=public-fixture-password',
                            '-cp', classpath, 'org.eyepqc.mobile.AccountNetworkCli', str(public),
                            hashlib.sha256(reference.G6.pk).hexdigest(), f'wss://localhost:{port}/stream',
                            'fixture-user', 'public-fixture-password', expected, *([] if mode=='normal' else [mode]),
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                        try:
                            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
                        finally:
                            if process.returncode is None:
                                process.kill(); await process.wait()
                        self.assertEqual(process.returncode, 0, (stdout+stderr).decode(errors='replace'))
                        for _ in range(150):
                            if not relay.busy: break
                            await asyncio.sleep(.02)
                        self.assertFalse(relay.busy)
                        self.assertTrue(devices[-1].closed)
                        self.assertEqual([int(x) for x in devices[-1].commands[:6]], [1,3,5,11,5,6])
                        self.assertEqual(len(devices[-1].board.offers), 2 if mode in ('rekey','timer') else 1)
                        if mode in ('rekey','timer'):
                            self.assertNotEqual(devices[-1].board.offers[0], devices[-1].board.offers[1])
                        print('ACCOUNT_THREE_END_OK mode='+mode, flush=True)
                finally:
                    if tunnel is not None:
                        await tunnel.close()
                    server.close(); await server.wait_closed()
                    if tunnel is not None:
                        self.assertGreater(tunnel.upload_bytes, 0)
                        self.assertGreater(tunnel.download_bytes, 0)
            finally:
                if os.name == 'nt':
                    import _ctypes
                    _ctypes.FreeLibrary(lib._handle)
                del lib


if __name__ == '__main__':
    unittest.main(verbosity=2)
