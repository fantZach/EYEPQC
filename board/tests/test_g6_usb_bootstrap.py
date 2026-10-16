"""Offline-only real C/ML-KEM bootstrap and profile-builder rejection tests."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class BootstrapTests(unittest.TestCase):
    def test_actual_sdk_rx_cpu_buffers(self):
        workspace = ROOT / 'build/vitis/g6_handshake_recovery_20261015_1'
        sdk = Path('D:/AmdDesignTools/2026.1/Vitis/data/embeddedsw')
        includes = [ROOT / 'board/src/ps/diag', workspace / 'usb_bounded_sdk/src',
                    workspace / 'bsp/ps7_cortexa9_0/include', ROOT / 'board/src/ps/include',
                    ROOT / 'board/src/third_party', ROOT / 'board/prj',
                    sdk / 'XilinxProcessorIPLib/drivers/usbps_v2_11/examples',
                    sdk / 'lib/bsp/standalone_v9_5/src/common/intr']
        with tempfile.TemporaryDirectory() as directory:
            for optimization in ('-O0', '-O3'):
                with self.subTest(optimization=optimization):
                    output = Path(directory) / (optimization[1:] + '-rx.exe')
                    command = ['C:/msys64/ucrt64/bin/gcc.exe', '-std=c11', optimization, '-Wall', '-Wextra',
                               '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                               '-DG6_USB_NATIVE_TEST', '-U__arm__']
                    command += [item for include in includes for item in ('-I', str(include))]
                    result = subprocess.run(command + [str(ROOT / 'board/tests/g6_usb_bootstrap_rx_harness.c'),
                                                       '-o', str(output)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(output)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('G6_BOOTSTRAP_ACTUAL_RX_WIPE_PASS', result.stdout)

    def test_real_firmware_and_mlkem(self):
        compiler = Path('C:/msys64/ucrt64/bin/gcc.exe')
        self.assertTrue(compiler.is_file())
        with tempfile.TemporaryDirectory(prefix='eyepqc-bootstrap-') as temporary:
            directory = Path(temporary)
            (directory / 'xil_printf.h').write_text('int xil_printf(const char *, ...);\n')
            (directory / 'xtime_l.h').write_text(
                '#include <stdint.h>\ntypedef uint64_t XTime;\n'
                '#define COUNTS_PER_SECOND 1000000ULL\nvoid XTime_GetTime(XTime *);\n')
            (directory / 'xil_cache.h').write_text(
                '#include <stdint.h>\ntypedef uintptr_t UINTPTR;\n'
                'void Xil_DCacheFlushRange(uintptr_t,unsigned);\n')
            (directory / 'xil_io.h').write_text(
                '#include <stdint.h>\nuint32_t Xil_In32(uintptr_t);\n')
            includes = [directory, ROOT / 'board/src/ps/include',
                        ROOT / 'board/src/third_party', ROOT / 'board/src/third_party/mlkem',
                        ROOT / 'board/src/third_party/tinycrypt/lib/include']
            sources = [ROOT / 'board/tests/g6_usb_bootstrap_harness.c']
            sources += [ROOT / 'board/src/ps/src' / name for name in
                        ('session.c', 'protocol.c', 'ephemeral.c', 'm09_mlkem.c')]
            sources += [ROOT / 'board/src/third_party/tinycrypt/lib/source' / name
                        for name in ('sha256.c', 'utils.c')]
            for optimization in ('-O0', '-O3'):
                with self.subTest(optimization=optimization):
                    output = directory / (optimization[1:] + '.exe')
                    command = [str(compiler), '-std=c11', optimization, '-Wall', '-Wextra',
                               '-Werror', '-ffunction-sections', '-fdata-sections',
                               '-Wl,--gc-sections', '-DG6_DEV_USB_BOOTSTRAP', '-DG6_SECURE_CLEANUP']
                    command += [item for include in includes for item in ('-I', str(include))]
                    result = subprocess.run(command + list(map(str, sources)) + ['-o', str(output)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(output)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('G6_USB_BOOTSTRAP_REAL_FIRMWARE_PASS', result.stdout)

    def test_cli_rejects_mixed_profiles_before_tools_or_output(self):
        for conflict in ('--g6-dev-secure-cleanup', '--g6-production-provider=missing.c'):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'must-not-exist'
                result = subprocess.run([os.sys.executable, str(ROOT / 'board/prj/build_software.py'),
                                         '--xsa', 'absent.xsa', '--output', str(target),
                                         '--apps', 'g6_usb', '--g6-dev-usb-bootstrap', conflict],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('cannot mix', result.stderr)
                self.assertFalse(target.exists())

    def test_disabled_sd0_xsa_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            xsa = path / 'no-sd.xsa'
            with zipfile.ZipFile(xsa, 'w') as archive:
                archive.writestr('sysdef.xml', '<SYSTEM><SYSTEMINFO PART="xc7z020clg400-2"/></SYSTEM>')
                archive.writestr('system.hwh', '<SYSTEM><MODULE MODTYPE="processing_system7"><PARAMETERS>'
                                 '<PARAMETER NAME="PCW_SD0_PERIPHERAL_ENABLE" VALUE="0"/>'
                                 '</PARAMETERS></MODULE></SYSTEM>')
                archive.writestr('m01.bit', b'fixture')
                archive.writestr('ps7_init.tcl', b'fixture')
            target = path / 'must-not-exist'
            result = subprocess.run([os.sys.executable, str(ROOT / 'board/prj/build_software.py'),
                                     '--xsa', str(xsa), '--output', str(target), '--apps', 'g6_usb',
                                     '--g6-dev-usb-bootstrap', '--boot-images'],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('enable SD0', result.stderr)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
