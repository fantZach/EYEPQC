"""Synthetic keys and fake CDC only; never open a physical board or actual user secrets."""
import asyncio
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/host'))
import dev_usb_bootstrap as boot
import eyepqc
import relay
from private_acl import private_acl


def status_record(state, offset, pin=bytes(32), *, code=0):
    body = bytes((state, code)) + pin
    return boot.OUTER.pack(1, 46) + boot.HEADER.pack(b'EYBS', 1, boot.STATUS, offset, 34, boot.TOTAL) + body


class FakeDevice:
    def __init__(self, pin, *, ready=False, response=None, short_writes=False):
        self.pin, self.ready, self.response = pin, ready, response
        self.short_writes = short_writes
        self.input, self.pending, self.received = bytearray(), bytearray(), bytearray()
        self.records, self.references = [], []
        self.dtr, self.closed = False, False

    def reset_input_buffer(self):
        self.input.clear()

    def reset_output_buffer(self):
        pass

    def write(self, value):
        self.references.append(value)
        count = min(len(value), 17) if self.short_writes else len(value)
        self.pending.extend(value[:count])
        while len(self.pending) >= 3:
            channel, size = boot.OUTER.unpack_from(self.pending)
            if len(self.pending) < 3 + size:
                break
            record = bytes(self.pending[:size + 3])
            del self.pending[:size + 3]
            self.records.append(record)
            _, _, kind, offset, _, _ = boot.HEADER.unpack_from(record, 3)
            if self.response is not None:
                self.input.extend(self.response(kind, offset, record))
            elif kind == boot.QUERY:
                self.input.extend(status_record(boot.READY if self.ready else boot.WAIT,
                                               boot.TOTAL if self.ready else 0,
                                               self.pin if self.ready else bytes(32)))
            else:
                self.received.extend(record[15:])
                self.ready = len(self.received) == boot.TOTAL
                self.input.extend(status_record(boot.READY if self.ready else boot.RECV,
                                               len(self.received), self.pin if self.ready else bytes(32)))
        return count

    def read(self, size):
        size = min(size, 7)
        result = bytes(self.input[:size])
        del self.input[:size]
        return result

    def close(self):
        self.closed = True


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        private_acl(cls.root, protect=True)
        cls.public = bytes([0x23]) * 800
        cls.pin = hashlib.sha256(cls.public).digest()
        cls.key = bytes(768) + cls.public + hashlib.sha3_256(cls.public).digest() + bytes([0x58]) * 32
        cls.identity = cls.root / 'fixture-secret.bin'
        cls.identity.write_bytes(cls.key)
        cls.pairing = cls.root / 'pairing.json'
        cls.pairing.write_text(json.dumps(dict(version=2, endpoint='wss://localhost:8765/stream',
            public_key_hex=cls.public.hex(), public_key_sha256=cls.pin.hex())))

    def open(self, device, identity=None):
        with patch.object(boot.time, 'sleep'):
            return boot.open_bootstrapped('COM99', identity or self.identity, self.pairing,
                                         opener=lambda port: device)

    def test_wait_provisions_two_ordered_records_with_fresh_seed_and_erases_owned_buffers(self):
        erased = []
        real_erase = boot.erase
        def erase(value):
            real_erase(value)
            if value is not None:
                erased.append(value)
        with patch.object(boot.secrets, 'token_bytes', side_effect=[b'A' * 32, b'B' * 32]), patch.object(boot, 'erase', erase):
            devices = [FakeDevice(self.pin), FakeDevice(self.pin, short_writes=True)]
            for device in devices:
                self.assertIs(self.open(device), device)
                self.assertEqual(len(device.records), 3)
                self.assertEqual(boot.HEADER.unpack_from(device.records[1], 3)[3:5], (0, 1024))
                self.assertEqual(boot.HEADER.unpack_from(device.records[2], 3)[3:5], (1024, 672))
                self.assertEqual(device.received[:32], self.pin)
                self.assertEqual(device.received[32:1664], self.key)
                self.assertFalse(device.closed)
                boot.close_device(device)
                self.assertTrue(device.closed)
                self.assertFalse(device.dtr)
        self.assertEqual(devices[0].received[-32:], b'A' * 32)
        self.assertEqual(devices[1].received[-32:], b'B' * 32)
        self.assertTrue({32, 1633, 1696}.issubset({len(value) for value in erased}))
        self.assertTrue(all(not any(value) for value in erased))
        self.assertTrue(all(not any(reference) for device in devices for reference in device.references))

    def test_ready_only_queries_and_does_not_read_identity_or_generate_seed(self):
        device = FakeDevice(self.pin, ready=True)
        with patch.object(boot, 'private_material', side_effect=AssertionError('secret read')), patch.object(
                boot.secrets, 'token_bytes', side_effect=AssertionError('seed generation')):
            self.assertIs(self.open(device, self.root / 'missing'), device)
        self.assertEqual(len(device.records), 1)
        boot.close_device(device)

    def test_refuses_invalid_query_before_reading_or_sending_secrets(self):
        normal = bytearray(status_record(boot.WAIT, 0))
        corrupt = []
        for index in (0, 2, 3, 7, 8, 10, 12, 14):
            data = bytearray(normal)
            data[index] ^= 0x40
            corrupt.append(bytes(data))
        corrupt += [status_record(boot.WAIT, 1), status_record(boot.WAIT, 0, bytes([1]) * 32),
                    status_record(boot.RECV, 1), status_record(boot.FAULT, 0, code=1),
                    status_record(boot.READY, boot.TOTAL, bytes([1]) * 32)]
        for data in corrupt:
            with self.subTest(reply=data[:15]), patch.object(boot, 'private_material',
                    side_effect=AssertionError('secret read')):
                device = FakeDevice(self.pin, response=lambda *args: data)
                with self.assertRaises(ValueError):
                    self.open(device)
                self.assertEqual(len(device.records), 1)
                self.assertTrue(device.closed)
                self.assertFalse(device.dtr)

    def test_wrong_identity_acl_and_size_refuse_before_first_data(self):
        other = self.root / 'invalid-secret.bin'
        for content in (b'', self.key[:-1], self.key + b'x', bytes(1632)):
            other.write_bytes(content)
            device = FakeDevice(self.pin)
            with self.assertRaises(ValueError):
                self.open(device, other)
            self.assertEqual(len(device.records), 1)
            self.assertTrue(device.closed)
        with patch.object(boot, 'private_acl', side_effect=PermissionError('synthetic')):
            device = FakeDevice(self.pin)
            with self.assertRaises(PermissionError):
                self.open(device)
            self.assertEqual(len(device.records), 1)

    def test_nist_mlkem_secret_hash_is_sha3_but_application_pin_remains_sha256(self):
        root = Path(__file__).resolve().parents[2]
        vectors = json.loads((root / 'data/kat/nist_mlkem512.json').read_text())
        vector = vectors['encapsulation'][0]
        public, key = bytes.fromhex(vector['ek']), bytes.fromhex(vector['dk'])
        pin = hashlib.sha256(public).digest()
        self.assertEqual(key[768:1568], public)
        self.assertEqual(key[1568:1600], hashlib.sha3_256(public).digest())
        self.assertNotEqual(key[1568:1600], pin)
        identity = self.root / 'nist-acvp-test-key.bin'
        identity.write_bytes(key)
        loaded = boot.private_material(identity, public, pin)
        self.assertEqual(loaded[:boot.SECRET_KEY_SIZE], key)
        boot.erase(loaded)
        identity.write_bytes(key[:1568] + pin + key[1600:])
        with self.assertRaises(ValueError):
            boot.private_material(identity, public, pin)

    def test_bad_ack_stops_without_second_data_and_erases_buffers(self):
        erased = []
        real_erase = boot.erase
        def erase(value):
            real_erase(value)
            if value is not None:
                erased.append(value)
        def response(kind, offset, record):
            return status_record(boot.WAIT, 0) if kind == boot.QUERY else status_record(boot.RECV, 1)
        device = FakeDevice(self.pin, response=response)
        with patch.object(boot, 'erase', erase), self.assertRaises(ValueError):
            self.open(device)
        self.assertEqual(len(device.records), 2)
        self.assertTrue(device.closed)
        self.assertTrue(all(not any(value) for value in erased))

    def test_explicit_port_required_before_opening(self):
        for port in (None, '', 'auto'):
            with self.assertRaises(ValueError):
                boot.open_bootstrapped(port, self.identity, self.pairing,
                    opener=lambda port: self.fail('must not enumerate/open'))

    def test_absolute_timeout_and_short_write_are_bounded_and_erase(self):
        device = FakeDevice(self.pin, ready=True)
        with patch.object(boot.time, 'monotonic', return_value=10), self.assertRaises(TimeoutError):
            boot.write_record(device, boot.DATA, 0, b'fixture', 10)
        self.assertEqual(device.records, [])
        with patch.object(device, 'write', return_value=0), self.assertRaises(OSError):
            boot.write_record(device, boot.DATA, 0, b'fixture', float('inf'))
        with patch.object(boot.time, 'monotonic', return_value=10), self.assertRaises(TimeoutError):
            boot.read_exact(device, 3, 10)

    def test_network_control_rejects_bootstrap(self):
        query = boot.OUTER.pack(1, 12) + boot.HEADER.pack(b'EYBS', 1, boot.QUERY, 0, 0, boot.TOTAL)
        with self.assertRaises(ValueError):
            relay.control_record(query)


class CliBootstrapTests(unittest.TestCase):
    def run_command(self, options, settings=None, bootstrap_error=None):
        settings = settings or SimpleNamespace(serial_port='COM99', pairing_file=Path('fixture-pairing'))
        factory = unittest.mock.Mock(return_value=FakeDevice(bytes(32), ready=True), side_effect=bootstrap_error)
        out, err = io.StringIO(), io.StringIO()
        with patch.object(eyepqc, 'ensure_port_free') as port, patch.object(
                eyepqc, 'load_config', return_value=(settings, None)), patch.object(
                eyepqc, 'check_materials'), patch.object(boot, 'open_bootstrapped', factory), patch.object(
                eyepqc, 'run_services', new=AsyncMock()) as services, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = eyepqc.main(['run', *options])
        return result, out.getvalue() + err.getvalue(), factory, services, port

    def test_normal_run_never_probes_usb_or_reads_dev_key(self):
        code, _, factory, services, _ = self.run_command([])
        self.assertEqual(code, 0)
        factory.assert_not_called()
        services.assert_awaited_once()

    def test_explicit_flags_pair_and_port_are_required(self):
        for options in (['--dev-usb-bootstrap'], ['--dev-identity-file', 'secret.bin']):
            code, _, factory, services, _ = self.run_command(options)
            self.assertEqual(code, 1)
            factory.assert_not_called()
            services.assert_not_awaited()
        code, _, factory, services, _ = self.run_command(
            ['--dev-usb-bootstrap', '--dev-identity-file', 'secret.bin'],
            settings=SimpleNamespace(serial_port=None, pairing_file=Path('fixture')))
        self.assertEqual(code, 1)
        factory.assert_not_called()
        services.assert_not_awaited()

    def test_bootstrap_completes_and_closes_before_services_and_sets_reconnect_factory(self):
        settings = SimpleNamespace(serial_port='COM99', pairing_file=Path('fixture'))
        code, output, factory, services, _ = self.run_command(
            ['--dev-usb-bootstrap', '--dev-identity-file', 'secret.bin'], settings=settings)
        self.assertEqual(code, 0)
        self.assertTrue(factory.return_value.closed)
        self.assertIn('DEV_USB_READY', output)
        self.assertTrue(callable(settings.dev_bootstrap_factory))
        services.assert_awaited_once()

    def test_fail_closed_redacts_failure_and_never_starts_listener(self):
        code, output, _, services, _ = self.run_command(
            ['--dev-usb-bootstrap', '--dev-identity-file', 'secret.bin'],
            bootstrap_error=ValueError('never-print-fixture-secret'))
        self.assertEqual(code, 1)
        self.assertNotIn('never-print-fixture-secret', output)
        self.assertIn('no listener started', output)
        services.assert_not_awaited()

    def test_existing_listener_refuses_before_config_or_secret_or_usb(self):
        with patch.object(eyepqc, 'ensure_port_free', side_effect=eyepqc.ServiceError('already occupied')), patch.object(
                eyepqc, 'load_config', side_effect=AssertionError('must not read configured files')), patch.object(
                boot, 'open_bootstrapped', side_effect=AssertionError('must not touch USB')), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(eyepqc.main(['run', '--dev-usb-bootstrap', '--dev-identity-file', 'secret.bin']), 1)


class PreparationCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_preparation_waits_then_closes_only_its_owned_handle(self):
        started, finish = threading.Event(), threading.Event()
        device = FakeDevice(bytes(32), ready=True)
        def factory():
            started.set()
            if not finish.wait(2):
                raise TimeoutError('fixture wait')
            return device
        relay_instance = relay.Relay('fixture-token', factory, prepare_serial=True)
        socket = SimpleNamespace(remote_address='fixture', close=AsyncMock(), close_code=None)
        task = asyncio.create_task(relay_instance.handle(socket))
        await asyncio.to_thread(started.wait, 1)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(device.closed)
        finish.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(device.closed)
        self.assertFalse(device.dtr)


class WireInterop(unittest.TestCase):
    def test_actual_pc_packets_and_c_state_machine_replies(self):
        root = Path(__file__).resolve().parents[2]
        compiler = Path('C:/msys64/ucrt64/bin/gcc.exe')
        if not compiler.is_file():
            self.skipTest('local native compiler not installed; no download attempted')
        source = root / 'board/tests/bootstrap_wire_fixture.c'
        self.assertTrue(source.is_file())
        pin = hashlib.sha256(bytes(800)).digest()
        material = bytearray(pin + bytes(1632) + bytes(32))
        def packet(kind, offset=0, body=b''):
            sink = SimpleNamespace(output=bytearray())
            def write(data):
                sink.output.extend(data)
                return len(data)
            sink.write = write
            boot.write_record(sink, kind, offset, body, time.monotonic() + 1)
            return bytes(sink.output[3:])
        query = packet(boot.QUERY)
        first = packet(boot.DATA, 0, material[:1024])
        last = packet(boot.DATA, 1024, material[1024:])
        wrong = packet(boot.DATA, 1025, material[1024:])
        with tempfile.TemporaryDirectory(prefix='eyepqc-wire-') as temporary:
            fixture = Path(temporary) / 'bootstrap-wire.exe'
            result = subprocess.run([str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                '-I', str(root / 'board/src/ps/include'), str(source), '-o', str(fixture)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            for records, expected in (([query, first, last, query], [boot.WAIT, boot.RECV, boot.READY, boot.READY]),
                    ([query, first, wrong, query], [boot.WAIT, boot.RECV, boot.FAULT, boot.FAULT]),
                    ([query, first, last, query, first, query],
                     [boot.WAIT, boot.RECV, boot.READY, boot.READY, boot.FAULT, boot.FAULT])):
                result = subprocess.run([str(fixture)], input=''.join(record.hex() + '\n' for record in records),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                replies = [bytes.fromhex(line) for line in result.stdout.splitlines()]
                self.assertEqual(len(replies), len(expected))
                for reply, state in zip(replies, expected):
                    self.assertEqual(len(reply), 46)
                    self.assertEqual(reply[12], state)
                    device = FakeDevice(pin)
                    device.input.extend(boot.OUTER.pack(1, len(reply)) + reply)
                    if state == boot.FAULT:
                        self.assertEqual(reply[12:14], b'\x03\x01')
                        with self.assertRaises(ValueError):
                            boot.status(device, time.monotonic() + 1)
                    else:
                        actual, offset, actual_pin = boot.status(device, time.monotonic() + 1)
                        self.assertEqual(actual, state)
                        self.assertEqual(offset, {boot.WAIT: 0, boot.RECV: 1024, boot.READY: 1696}[state])
                        self.assertEqual(actual_pin, pin if state == boot.READY else bytes(32))


if __name__ == '__main__':
    unittest.main()
