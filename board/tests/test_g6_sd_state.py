from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sim/tb'))
from test_g6_hmac_drbg import find_compiler, INCLUDES, SOURCES


class SdStateTests(unittest.TestCase):
    def test_build_profile_and_sd0_guard_before_output(self):
        with tempfile.TemporaryDirectory(prefix='eyepqc-sd-profile-') as temp:
            base = Path(temp)
            for conflict in ('--g6-dev-usb-bootstrap', '--g6-dev-secure-cleanup',
                             '--g6-production-provider=absent.c'):
                target = base / 'must-not-exist'
                result = subprocess.run([sys.executable, str(ROOT / 'board/prj/build_software.py'),
                                         '--xsa', 'absent.xsa', '--output', str(target),
                                         '--apps', 'g6_usb', '--g6-sd-identity', conflict],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('excludes', result.stderr)
                self.assertFalse(target.exists())
            xsa = base / 'no-sd.xsa'
            with zipfile.ZipFile(xsa, 'w') as archive:
                archive.writestr('sysdef.xml', '<SYSTEM><SYSTEMINFO PART="xc7z020clg400-2"/></SYSTEM>')
                archive.writestr('system.hwh', '<SYSTEM><MODULE MODTYPE="processing_system7"><PARAMETERS>'
                                 '<PARAMETER NAME="PCW_SD0_PERIPHERAL_ENABLE" VALUE="0"/>'
                                 '</PARAMETERS></MODULE></SYSTEM>')
                archive.writestr('m01.bit', b'fixture')
                archive.writestr('ps7_init.tcl', b'fixture')
            result = subprocess.run([sys.executable, str(ROOT / 'board/prj/build_software.py'),
                                     '--xsa', str(xsa), '--output', str(base / 'must-not-exist'),
                                     '--apps', 'g6_usb', '--g6-sd-identity'],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('enable SD0', result.stderr)
            self.assertFalse((base / 'must-not-exist').exists())

    def test_ratchet_reboot_failure_and_corruption(self):
        compiler = find_compiler()
        self.assertTrue(compiler)
        with tempfile.TemporaryDirectory(prefix='eyepqc-sd-state-') as temp:
            executable = Path(temp) / 'sd_state.exe'
            sources = [ROOT / 'board/tests/g6_sd_state_harness.c',
                       ROOT / 'board/src/ps/src/g6_sd_state.c', *SOURCES[1:]]
            command = [compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror']
            for include in INCLUDES:
                command += ['-I', str(include)]
            command += [str(p) for p in sources] + ['-o', str(executable)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('G6_SD_STATE_PASS', result.stdout)

    def test_fatfs_adapter_and_bounded_host_idle(self):
        compiler = find_compiler()
        self.assertTrue(compiler)
        with tempfile.TemporaryDirectory(prefix='eyepqc-sd-adapter-') as temp:
            base = Path(temp)
            (base / 'ff.h').write_text('''#include <stdint.h>
typedef struct { unsigned size; unsigned index; } FIL;
typedef struct { int ignored; } FATFS;
typedef unsigned UINT;
#define FR_OK 0
#define FA_READ 1
#define FA_WRITE 2
#define f_size(f) ((f)->size)
int f_mount(FATFS *, const char *, int);
int f_open(FIL *, const char *, int);
int f_read(FIL *, void *, unsigned, UINT *);
int f_write(FIL *, const void *, unsigned, UINT *);
int f_close(FIL *);
int f_sync(FIL *);
''')
            (base / 'xtime_l.h').write_text('''#include <stdint.h>
typedef uint64_t XTime;
#define COUNTS_PER_SECOND 10U
void XTime_GetTime(XTime *);
''')
            (base / 'xparameters.h').write_text('#define XPAR_PS7_SD_0_BASEADDR 0xE0100000U\n')
            (base / 'xsdps_hw.h').write_text('''#include <stdint.h>
#define XSDPS_PRES_STATE_OFFSET 0x24U
#define XSDPS_PSR_INHIBIT_CMD_MASK 1U
#define XSDPS_PSR_INHIBIT_DAT_MASK 2U
#define XSDPS_PSR_DAT_ACTIVE_MASK 4U
#define XSDPS_PSR_DAT30_SG_LVL_MASK 0x00F00000U
uint32_t mock_sd_read(void);
#define XSdPs_ReadReg(base, offset) mock_sd_read()
''')
            executable = base / 'sd_adapter.exe'
            sources = [ROOT / 'board/tests/g6_sd_identity_harness.c',
                       ROOT / 'board/src/ps/src/g6_sd_identity.c',
                       ROOT / 'board/src/ps/src/g6_sd_state.c', *SOURCES[1:]]
            command = [compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(base)]
            for include in INCLUDES:
                command += ['-I', str(include)]
            command += [str(p) for p in sources] + ['-o', str(executable)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('G6_SD_ADAPTER_PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
