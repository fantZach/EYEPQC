import unittest

from prj.run_keccak_sponge_x4_board_benchmark import capture_uart


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        value = self.value
        self.value += 0.6
        return value


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.read_count = 0

    def read(self, _size):
        self.read_count += 1
        return self.chunks.pop(0) if self.chunks else b""


class FakeProcess:
    def __init__(self, returncode):
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.returncode = -9


class BoardCaptureTests(unittest.TestCase):
    def test_waits_for_firmware_marker_after_successful_xsdb_exit(self):
        ser = FakeSerial([b"", b"", b"KECCAK_SX4_BENCH_DONE\r\n"])
        proc = FakeProcess(0)

        raw, code, _elapsed = capture_uart(ser, proc, timeout=10,
                                            started_at=0.0, clock=FakeClock())

        self.assertEqual(code, 0)
        self.assertEqual(ser.read_count, 3)
        self.assertIn(b"KECCAK_SX4_BENCH_DONE", raw)

    def test_stops_early_on_xsdb_failure(self):
        ser = FakeSerial([b""] * 5)
        proc = FakeProcess(1)

        raw, code, _elapsed = capture_uart(ser, proc, timeout=10,
                                            started_at=0.0, clock=FakeClock())

        self.assertEqual(code, 1)
        self.assertEqual(raw, b"")
        self.assertEqual(ser.read_count, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
