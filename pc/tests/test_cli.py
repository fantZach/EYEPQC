"""CLI supervision/configuration checks; no production files, USB or SSH connection."""

import asyncio
import contextlib
import io
import json
import hashlib
import datetime as dt
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import eyepqc
import relay


class Child:
    def __init__(self):
        self.returncode = None
        self.ended = asyncio.Event()
        self.terminated = False

    async def wait(self):
        await self.ended.wait()
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0
        self.ended.set()


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_spawn_reaps_child_created_after_cancellation(self):
        spawning, finish_spawn, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        child = Child()

        async def fake_relay(args, *, ready):
            ready.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        async def spawn(*args, **kwargs):
            spawning.set()
            await finish_spawn.wait()
            return child

        with patch.object(eyepqc.relay, 'run', fake_relay), patch.object(eyepqc.asyncio, 'create_subprocess_exec', spawn):
            task = asyncio.create_task(eyepqc.run_services(None, ['fixture-ssh']))
            await asyncio.wait_for(spawning.wait(), 1)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            finish_spawn.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(child.terminated)
        self.assertTrue(stopped.is_set())

    async def test_cancellation_stops_only_owned_child_and_relay(self):
        stopped = asyncio.Event()
        spawned = asyncio.Event()
        child = Child()

        async def fake_relay(args, *, ready):
            ready.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        async def spawn(*args, **kwargs):
            spawned.set()
            return child

        with patch.object(eyepqc.relay, 'run', fake_relay), patch.object(eyepqc.asyncio, 'create_subprocess_exec', spawn):
            task = asyncio.create_task(eyepqc.run_services(None, ['fixture-ssh']))
            await asyncio.wait_for(spawned.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(child.terminated)
        self.assertTrue(stopped.is_set())

    async def test_ssh_failure_stops_relay(self):
        stopped = asyncio.Event()
        child = Child()
        child.returncode = 255
        child.ended.set()

        async def fake_relay(args, *, ready):
            ready.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        with patch.object(eyepqc.relay, 'run', fake_relay), patch.object(
                eyepqc.asyncio, 'create_subprocess_exec', AsyncMock(return_value=child)):
            with self.assertRaisesRegex(RuntimeError, 'SSH exited with code 255'):
                await eyepqc.run_services(None, ['fixture-ssh'])
        self.assertTrue(stopped.is_set())

    async def test_ready_failure_never_starts_ssh(self):
        async def fail(args, *, ready):
            raise RuntimeError('fixture startup failure')

        spawn = AsyncMock()
        with patch.object(eyepqc.relay, 'run', fail), patch.object(eyepqc.asyncio, 'create_subprocess_exec', spawn):
            with self.assertRaisesRegex(RuntimeError, 'startup failure'):
                await eyepqc.run_services(None, ['fixture-ssh'])
        spawn.assert_not_called()

    async def test_cancel_before_ready_leaves_no_child_or_relay(self):
        entered, stopped = asyncio.Event(), asyncio.Event()

        async def starting(args, *, ready):
            entered.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

        spawn = AsyncMock()
        with patch.object(eyepqc.relay, 'run', starting), patch.object(eyepqc.asyncio, 'create_subprocess_exec', spawn):
            task = asyncio.create_task(eyepqc.run_services(None, ['fixture-ssh']))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(stopped.is_set())
        spawn.assert_not_called()

    async def test_old_relay_run_api_and_optional_ready_signal(self):
        args = SimpleNamespace(tls_cert=None, tls_key=None, token_file='fixture-token', accounts_file=None,
                               pairing_file=None, host='127.0.0.1', port=0)
        signal = asyncio.Event()
        entered = asyncio.Event()

        class Server:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def serve_forever(self):
                entered.set()
                await asyncio.Future()

        for kwargs in ({}, {'ready': signal}):
            entered.clear()
            with patch.object(relay.Relay, 'start', AsyncMock(return_value=Server())), patch.object(
                    relay, 'read_token', return_value='fixture-test-token-' * 3):
                task = asyncio.create_task(relay.run(args, **kwargs))
                await asyncio.wait_for(entered.wait(), 1)
                if kwargs:
                    self.assertTrue(signal.is_set())
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'eyepqc.json'
        for name in ('accounts', 'pairing', 'cert', 'key', 'identity', 'known_hosts'):
            (self.root / name).write_text('fixture', encoding='ascii')
        self.record = dict(version=1, serial_port=None, accounts_file='accounts', pairing_file='pairing',
                           tls_cert='cert', tls_key='key', tunnel=None)

    def save(self):
        self.config.write_text(json.dumps(self.record), encoding='utf-8')

    def test_paths_resolve_relative_to_config_not_working_directory(self):
        self.save()
        args, ssh = eyepqc.load_config(self.config)
        self.assertEqual(args.accounts_file, self.root / 'accounts')
        self.assertEqual(args.pairing_file, self.root / 'pairing')
        self.assertIsNone(ssh)
        self.assertEqual(args.host, '127.0.0.1')

    def test_strict_fields_types_and_paths(self):
        original = self.record.copy()
        for key, value in (('version', True), ('serial_port', 'COM7\n'), ('tunnel', {}),
                           ('accounts_file', '//remote/share/secret'), ('tls_key', 'missing'),
                           ('password', 'never-inline')):
            with self.subTest(key=key):
                self.record = original | {key: value}
                self.save()
                with self.assertRaises((ValueError, OSError)):
                    eyepqc.load_config(self.config)
        self.config.write_text('{"version":1,"version":1}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            eyepqc.load_config(self.config)
        self.config.write_bytes(b' ' * 16385)
        with self.assertRaisesRegex(ValueError, '16 KiB'):
            eyepqc.load_config(self.config)

    def test_tunnel_passes_literal_paths_without_reading_private_contents(self):
        self.record['tunnel'] = dict(host='example.org', ssh_port=2222,
                                     identity_file='identity', known_hosts='known_hosts')
        self.save()
        with patch.object(eyepqc.cloud_tunnel, 'command', return_value=['fixture-ssh']) as command:
            _, ssh = eyepqc.load_config(self.config)
        self.assertEqual(ssh, ['fixture-ssh'])
        self.assertEqual(command.call_args.args, ('example.org', self.root / 'identity', self.root / 'known_hosts', 2222))

    def test_listener_refusal_before_any_secret_or_process_read(self):
        output = io.StringIO()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                eyepqc.ensure_port_free(listener.getsockname()[1])
        with patch.object(eyepqc, 'ensure_port_free', side_effect=RuntimeError('occupied')), patch.object(
                eyepqc, 'load_config') as load, contextlib.redirect_stderr(output):
            self.assertEqual(eyepqc.main(['run', '--config', str(self.config)]), 1)
        load.assert_not_called()

    def test_errors_do_not_echo_secrets_and_account_refuses_overwrite(self):
        secret = 'fixture-secret-do-not-print'
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(eyepqc, 'load_config', side_effect=ValueError(secret)), contextlib.redirect_stdout(
                output), contextlib.redirect_stderr(errors):
            self.assertEqual(eyepqc.main(['check', '--config', str(self.config)]), 1)
        self.assertNotIn(secret, output.getvalue() + errors.getvalue())
        existing = self.root / 'accounts'
        with patch.object(eyepqc.getpass, 'getpass') as prompt, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(eyepqc.main(['account', '--file', str(existing), '--username', 'viewer']), 1)
        prompt.assert_not_called()
        self.assertEqual(existing.read_text(), 'fixture')


class FrozenTests(unittest.TestCase):
    def test_built_executable_checks_isolated_fixture_without_network(self):
        exe = Path(__file__).resolve().parents[2] / 'build/pc_cli/dist/eyepqc.exe'
        if not exe.is_file():
            self.skipTest('build EXE first with pc/build_exe.ps1')
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = ec.generate_private_key(ec.SECP256R1())
            subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'offline-fixture')])
            now = dt.datetime.now(dt.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                    .public_key(key.public_key()).serial_number(1)
                    .not_valid_before(now - dt.timedelta(minutes=1))
                    .not_valid_after(now + dt.timedelta(days=1)).sign(key, hashes.SHA256()))
            (root / 'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            (root / 'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            public = bytes(800)
            (root / 'pairing.json').write_text(json.dumps(dict(version=2, endpoint='wss://localhost:8765/stream',
                public_key_hex=public.hex(), public_key_sha256=hashlib.sha256(public).hexdigest())))
            (root / 'accounts.json').write_text(json.dumps({'fixture': {'salt': '00' * 16, 'hash': '00' * 32}}))
            config = dict(version=1, serial_port=None, accounts_file='accounts.json', pairing_file='pairing.json',
                          tls_cert='cert.pem', tls_key='key.pem', tunnel=None)
            (root / 'eyepqc.json').write_text(json.dumps(config))
            result = subprocess.run([str(exe), 'check', '--config', str(root / 'eyepqc.json')],
                                    capture_output=True, text=True, timeout=30, cwd=root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('CONFIG_OK offline_only=true', result.stdout)
            self.assertNotIn('PRIVATE KEY', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
