import asyncio, base64, datetime, hashlib, http.client, io, ipaddress, json, logging, ssl, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
from accounts import Accounts, create_account, password_hash
from relay import Relay, control_record, read_pairing
from protocol import encode_control, encode_usb_record, decode_control
from prepare_pairing import configuration, export_config
from test_relay import FakeSerial, HELLO, ACK
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def basic(user='测试', password='fixture-password'):
    return 'Basic ' + base64.b64encode((user + ':' + password).encode()).decode()


class AccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        create_account(self.root/'accounts.json', '测试', 'fixture-password')
        self.accounts = Accounts(self.root/'accounts.json')
        self.accounts.users['other'] = self.accounts.users['测试']
        self.devices = []
        def factory():
            device = FakeSerial()
            self.devices.append(device)
            return device
        self.public_config = dict(version=2, endpoint='wss://127.0.0.1/stream',
                                  public_key_hex=bytes(800).hex(),
                                  public_key_sha256=hashlib.sha256(bytes(800)).hexdigest())
        self.pairing_path = self.root/'pairing.json'
        self.pairing_path.write_text(json.dumps(self.public_config), encoding='utf-8')
        self.relay = Relay(accounts=self.accounts, serial_factory=factory, pairing_file=self.pairing_path)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
                .not_valid_after(now+datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
                .sign(key, hashes.SHA256()))
        (self.root/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        (self.root/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(self.root/'cert.pem', self.root/'key.pem')
        self.client_tls = ssl.create_default_context(cafile=str(self.root/'cert.pem'))
        self.server = await self.relay.start('127.0.0.1', 0, tls=tls)
        self.url = 'wss://127.0.0.1:' + str(self.server.sockets[0].getsockname()[1]) + '/stream'

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    def client(self, suffix='', header=None):
        return connect(self.url+suffix, ssl=self.client_tls, proxy=None,
                       additional_headers={'Authorization': header or basic()})

    async def ready(self):
        for _ in range(200):
            if self.devices and self.devices[-1].dtr:
                return self.devices[-1]
            await asyncio.sleep(.005)
        self.fail('not ready')

    async def pairing_request(self, path='/pairing.json', headers=None):
        def request():
            connection = http.client.HTTPSConnection('127.0.0.1', self.server.sockets[0].getsockname()[1],
                                                     context=self.client_tls, timeout=5)
            try:
                connection.request('GET', path, headers={'Authorization': basic()} if headers is None else headers)
                response = connection.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                connection.close()
        return await asyncio.to_thread(request)

    async def test_automatic_pairing_authenticates_without_opening_usb(self):
        status, headers, body = await self.pairing_request()
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), self.public_config)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertFalse(self.devices)
        self.assertFalse(self.relay.busy)

    async def test_automatic_pairing_rejects_bad_auth_paths_and_limits(self):
        for headers in ({}, {'Authorization': basic(password='wrong')}, {'Authorization': 'Bearer wrong'}):
            self.accounts.allowance = 5
            self.assertEqual((await self.pairing_request(headers=headers))[0], 401)
        for path in ('/pairing.json?takeover=1', '/private/login.txt', '/pairing.json/../accounts.json'):
            self.assertEqual((await self.pairing_request(path=path))[0], 404)
        self.accounts.allowance = 0
        self.assertEqual((await self.pairing_request())[0], 429)
        self.accounts.allowance = 5
        self.relay.verifying = True
        try:
            self.assertEqual((await self.pairing_request())[0], 429)
        finally:
            self.relay.verifying = False
        self.assertFalse(self.devices)

    async def test_pairing_download_cannot_take_over_or_touch_failed_usb(self):
        async with self.client() as old:
            device = await self.ready()
            owner = self.relay.owner
            for user in ('测试', 'other'):
                self.accounts.allowance = 5
                self.assertEqual((await self.pairing_request(headers={'Authorization': basic(user)}))[0], 200)
                self.assertIs(self.relay.owner, owner)
                self.assertFalse(device.closed)
                self.assertEqual(len(self.devices), 1)
        self.relay.cleanup_failed = True
        self.accounts.allowance = 5
        self.assertEqual((await self.pairing_request())[0], 200)

    async def test_protocol_debug_cannot_dump_basic_credentials(self):
        logger = logging.getLogger('eyepqc.relay.websocket')
        with patch.object(logger, 'level', logging.DEBUG), patch('relay.serve', new_callable=AsyncMock) as serve:
            await self.relay.start(tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER))
            self.assertFalse(serve.call_args.kwargs['logger'].isEnabledFor(logging.DEBUG))

    async def test_disconnect_during_password_verification_cancels_handshake_without_usb_or_assertion(self):
        started, release = threading.Event(), threading.Event()
        original = self.accounts.verify
        def delayed(header):
            started.set()
            if not release.wait(2):
                raise TimeoutError('fixture verifier wait')
            return original(header)
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        logger = logging.getLogger('eyepqc.relay.websocket')
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        port = self.server.sockets[0].getsockname()[1]
        with patch.object(self.accounts, 'verify', delayed):
            _, writer = await asyncio.open_connection('127.0.0.1', port, ssl=self.client_tls)
            try:
                request = ('GET /stream HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n'
                           'Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                           'Sec-WebSocket-Version: 13\r\nAuthorization: ' + basic() + '\r\n\r\n')
                writer.write(request.encode('ascii'))
                await writer.drain()
                self.assertTrue(await asyncio.to_thread(started.wait, 1))
                connection = next(iter(self.server.handlers))
                writer.transport.abort()
                await asyncio.wait_for(connection.wait_closed(), 1)
            finally:
                writer.transport.abort()
                release.set()
            for _ in range(200):
                if not self.relay.verifying and not self.server.handlers:
                    break
                await asyncio.sleep(.01)
            self.assertFalse(self.relay.verifying)
            self.assertFalse(self.server.handlers)
        self.assertFalse(self.devices)
        self.assertNotIn('AssertionError', output.getvalue())
        self.assertNotIn('unexpected internal error', output.getvalue())
        self.assertNotIn('opening handshake failed', output.getvalue())
        async with self.client():
            await self.ready()
            self.assertEqual(len(self.devices), 1)

    async def rejected(self, status, suffix='', header=None):
        self.accounts.allowance = 5
        with self.assertRaises(InvalidStatus) as caught:
            async with self.client(suffix, header):
                pass
        self.assertEqual(caught.exception.response.status_code, status)

    async def test_credentials_conflict_and_takeover(self):
        async with self.client() as old:
            first = await self.ready()
            await self.rejected(401, '?takeover=1', basic(password='wrong'))
            self.assertIs(self.relay.owner, next(iter(self.server.connections)))
            self.assertFalse(first.closed)
            await self.rejected(401, header='Bearer fixture')
            await self.rejected(409)
            await self.rejected(503, '?takeover=1', basic('other'))
            self.accounts.allowance = 5
            async with self.client('?takeover=1') as new:
                for _ in range(200):
                    if first.closed: break
                    await asyncio.sleep(.005)
                second = await self.ready()
                self.assertIsNot(first, second)
                self.assertTrue(first.closed)
                self.assertEqual(old.close_code, 4409)
                await new.send(HELLO)
                await asyncio.sleep(.05)
                self.assertEqual(first.written, [])
                self.assertEqual(second.written, [HELLO])
                offer = encode_usb_record(1, encode_control(10, bytes(864)))
                second.input.extend(offer)
                self.assertEqual(await asyncio.wait_for(new.recv(), 1), offer)
                reply = encode_usb_record(1, encode_control(11, bytes(832)))
                await new.send(reply)
                await asyncio.sleep(.05)
                self.assertEqual(second.written, [HELLO, reply])

    async def test_cleanup_failure_blocks_future_connections(self):
        old = await self.client()
        first = await self.ready()
        def fail_close():
            raise OSError('fixture cleanup failure')
        first.close = fail_close
        self.accounts.allowance = 5
        async with self.client('?takeover=1') as new:
            await asyncio.wait_for(new.wait_closed(), 3)
            self.assertEqual(new.close_code, 1011)
        self.assertTrue(self.relay.cleanup_failed)
        self.assertEqual(len(self.devices), 1)
        await self.rejected(503, '?takeover=1')
        await old.close()

    async def test_handoff_waits_for_old_read_and_fences_late_controls(self):
        old = await self.client()
        first = await self.ready()
        started = threading.Event()
        release = threading.Event()
        def blocked_read(size):
            started.set()
            release.wait(2)
            return b""
        first.read = blocked_read
        for _ in range(100):
            if started.is_set(): break
            await asyncio.sleep(.005)
        self.assertTrue(started.is_set())
        pending = asyncio.ensure_future(self.client('?takeover=1'))
        try:
            new = await pending
            for _ in range(100):
                if self.relay.owner is None: break
                await asyncio.sleep(.005)
            self.assertIsNone(self.relay.owner)
            self.assertEqual(len(self.devices), 1)
            class LateSocket:
                def __aiter__(self): return self
                async def __anext__(self): return HELLO
            await self.relay.network_reader(LateSocket(), first, {})
            self.assertEqual(first.written, [])
            release.set()
            for _ in range(200):
                if first.closed: break
                await asyncio.sleep(.005)
            second = await self.ready()
            self.assertIsNot(first, second)
            self.assertTrue(first.closed)
            await new.close()
        finally:
            release.set()
            await old.close()

    async def test_rate_limit_and_bounded_thread_keeps_loop_live(self):
        started = threading.Event()
        release = threading.Event()
        original = self.accounts.verify
        def delayed(header):
            started.set()
            release.wait(2)
            return original(header)
        with patch.object(self.accounts, 'verify', delayed):
            pending = asyncio.ensure_future(self.client())
            for _ in range(100):
                if started.is_set(): break
                await asyncio.sleep(.01)
            self.assertTrue(started.is_set())
            await self.rejected(429)
            release.set()
            ws = await pending
            await ws.close()
        self.accounts.allowance = 0
        with self.assertRaises(InvalidStatus) as caught:
            await self.client()
        self.assertEqual(caught.exception.response.status_code, 429)

    async def test_tls_and_unknown_account_dummy_hash(self):
        with self.assertRaises(ValueError):
            await self.relay.start('127.0.0.1', 0)
        with patch('accounts.password_hash', wraps=password_hash) as hashed:
            self.assertIsNone(await asyncio.to_thread(self.accounts.verify, basic('unknown')))
            self.assertEqual(hashed.call_count, 1)
        with self.assertRaises(ssl.SSLCertVerificationError):
            await connect(self.url, ssl=ssl.create_default_context(), proxy=None)
        with patch('accounts.hashlib.scrypt', return_value=bytes(32)) as hashed:
            password_hash('fixture', bytes(16))
            self.assertEqual(hashed.call_args.kwargs['n'], 131072)
            self.assertGreaterEqual(hashed.call_args.kwargs['maxmem'], 256*1024*1024)

    async def test_simultaneous_takeovers_keep_one_owner(self):
        old = await self.client()
        first = await self.ready()
        self.accounts.allowance = 5
        results = await asyncio.gather(self.client('?takeover=1'), self.client('?takeover=1'), return_exceptions=True)
        await asyncio.sleep(.4)
        self.assertTrue(first.closed)
        self.assertLessEqual(sum(not d.closed for d in self.devices), 1)
        owner = self.relay.owner
        self.assertIsNotNone(owner)
        for ws in results:
            if not isinstance(ws, Exception): await ws.close()
        await old.close()


class AccountPairingTests(unittest.TestCase):
    def test_served_pairing_is_strict_public_schema2_only(self):
        good = dict(version=2, endpoint='wss://viewer.example:8765/stream',
                    public_key_hex=bytes(800).hex(), public_key_sha256=hashlib.sha256(bytes(800)).hexdigest())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'pairing.json'
            payload = json.dumps(good).encode()
            path.write_bytes(payload)
            self.assertEqual(read_pairing(path), payload)
            with self.assertRaises(ValueError): Relay('x'*32, pairing_file=path)
            bad = []
            for field, value in [('version',1), ('version',True), ('endpoint','ws://localhost/stream'),
                                 ('endpoint','wss://user:pass@localhost/stream'),
                                 ('endpoint','wss://localhost:0/stream'), ('endpoint','wss://localhost:65536/stream'),
                                 ('endpoint','wss://localhost/stream?'), ('endpoint','wss://localhost/stream#'),
                                 ('public_key_hex','x'*1600), ('public_key_sha256','f'*64), ('public_key_hex',None)]:
                bad.append(json.dumps(dict(good, **{field:value})).encode())
            bad += [b'{}', b'[]', b'\xff', b' '*8193, payload+b'{}',
                    payload.replace(b'"version": 2', b'"version": 2, "version": 2'),
                    json.dumps(dict(good,password='never-serve')).encode(),
                    json.dumps(dict(good,token='never-serve')).encode()]
            for data in bad:
                with self.subTest(data=data[:60]):
                    path.write_bytes(data)
                    with self.assertRaises((ValueError, UnicodeError)): read_pairing(path)

    def test_schema2_and_new_control_direction(self):
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            public = bytes(800)
            (root/'public.bin').write_bytes(public)
            (root/'public.sha256').write_text(hashlib.sha256(public).hexdigest())
            result = configuration(root, 'wss://localhost/stream')
            self.assertEqual(set(result), {'version','endpoint','public_key_hex','public_key_sha256'})
            self.assertEqual(result['version'], 2)
            with self.assertRaises(ValueError): configuration(root, 'ws://localhost/stream')
            export_config(root, 'wss://localhost/stream', None, root/'pairing.json')
            self.assertEqual(json.loads((root/'pairing.json').read_text()), result)
        reply = encode_usb_record(1, encode_control(11, bytes(832)))
        self.assertEqual(control_record(reply), reply)
        with self.assertRaises(ValueError): control_record(encode_usb_record(1, encode_control(10, bytes(864))))
        for kind, size in [(10,864),(11,832)]:
            for wrong in [size-1,size+1]:
                with self.assertRaises(ValueError): encode_control(kind, bytes(wrong))
        self.assertEqual(decode_control(encode_control(1, b'\x01\x01\x00\x02'+bytes(32)))[0], 1)


if __name__ == '__main__': unittest.main()
