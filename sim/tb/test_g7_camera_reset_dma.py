import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'run_g7_camera_reset_dma', ROOT / 'board/prj/run_g7_camera_reset_dma.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CameraResetDmaRunner(unittest.TestCase):
    def test_both_workers_receive_the_selected_tool_root(self):
        command = runner.build_worker_command(
            Path('python.exe'), Path('workspace'), 30, False, Path('E:/fpg/2026.1'))
        self.assertIn('--tool-root', command)
        self.assertEqual(command[command.index('--tool-root') + 1], 'E:\\fpg\\2026.1')
        recovery = runner.build_worker_command(
            Path('python.exe'), Path('workspace'), 8, True, Path('E:/fpg/2026.1'))
        self.assertIn('--no-jtag', recovery)
        self.assertEqual(recovery[recovery.index('--tool-root') + 1], 'E:\\fpg\\2026.1')

    def test_frame_counter_waits_for_growth_then_a_quiet_window(self):
        class Clock:
            now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, duration):
                self.now += duration

        clock = Clock()
        values = iter([5, 6, 6, 6, 6])
        stable, samples = runner.wait_stable_frame_count(
            lambda: next(values), timeout=2.0, quiet_period=0.5, poll_interval=0.25,
            clock=clock.monotonic, sleep=clock.sleep)
        self.assertEqual(stable, 6)
        self.assertEqual([s['verified_frames'] for s in samples], [5, 6, 6, 6])

    def test_continuing_frames_do_not_count_as_stable(self):
        class Clock:
            now = 0.0

            def monotonic(self):
                return self.now

            def sleep(self, duration):
                self.now += duration

        clock = Clock()
        value = 0

        def growing():
            nonlocal value
            value += 1
            return value

        with self.assertRaises(TimeoutError):
            runner.wait_stable_frame_count(
                growing, timeout=1.0, quiet_period=0.5, poll_interval=0.25,
                clock=clock.monotonic, sleep=clock.sleep)


if __name__ == '__main__':
    unittest.main()
