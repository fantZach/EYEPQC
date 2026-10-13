"""Build a source-pinned candidate G6 firmware with bounded camera/DMA recovery."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "board/prj"))
import build_software as base

CPU_FLAGS = ['-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard']
VARIANT = 'g6-secure-buffer-cleanup-candidate014-safe-hello-ack-retry-v1'
LOOP_OLD = '''        if (status) {
            ++g6_capture_errors;
            ++g6_dropped;
            if (++capture_errors > 10 || g3_usb_flush()) fail_closed();
            continue;
        }'''
LOOP_NEW = '''        if (status == G6_AUTO_RECOVERED) {
            ++g6_capture_errors;
            ++g6_dropped;
            capture_errors = 0;
            g6_auto_recovery_diag.state = 2;
            continue;
        }
        if (status) {
            ++g6_capture_errors;
            ++g6_dropped;
            if (status == 16U) {
                fail_closed();
                continue;
            }
            if (status == 15U) {
                if (secure_cleanup() || g6_candidate_recover_camera()) {
                    mark_fault();
                    continue;
                }
                eye_session_error(&session);
                clear_handshake_cache();
                phase = WAIT_HELLO;
                capture_errors = 0;
                continue;
            }
            fail_closed();
            continue;
        }'''
TRANSPORT_OLD = '''        capture_errors = 0;
        status = send_frame(jpeg, size);
        if (g3_usb_resume() || status) {
            ++g6_transport_errors;
            fail_closed();
        }'''
TRANSPORT_NEW = '''        capture_errors = 0;
        uint32_t send_epoch = usb_cdc_connection_epoch();
        status = send_frame(jpeg, size);
        int resume_status = g3_usb_resume();
        if (!status && !resume_status)
            g6_transport_failure_diag.last_successful_frame_id = frame_id - 1U;
        if (resume_status || status) {
            g6_transport_failure_diag.send_status = (uint32_t)status;
            g6_transport_failure_diag.resume_status = (uint32_t)resume_status;
            g6_transport_failure_diag.phase = (uint32_t)phase;
            g6_transport_failure_diag.usb_ready = (uint32_t)usb_cdc_ready();
            g6_transport_failure_diag.connection_epoch = usb_cdc_connection_epoch();
            if (g6_secure_expected_usb_disconnect(
                    (unsigned)status, (unsigned)resume_status,
                    (unsigned)usb_cdc_ready(), send_epoch,
                    usb_cdc_connection_epoch())) {
                retire_disconnected_session();
                was_connected = 0;
                connection_epoch = usb_cdc_connection_epoch();
                continue;
            }
            g6_transport_failure_diag.transport_error_count = g6_transport_errors + 1U;
            ++g6_transport_errors;
            fail_closed();
        }'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_receiver_exit_cleanup_source(source):
    """Refuse candidate builds that count failed cleanup as a clean disconnect."""
    start = source.find('static int retire_disconnected_session(')
    end = source.find('\nstatic int handle_control', start)
    if start < 0 or end < 0:
        raise RuntimeError('Receiver-exit cleanup gate is missing from G6 source')
    body = source[start:end]
    try:
        failed_cleanup = body.split('if (secure_cleanup())', 1)[1].split('} else {', 1)[0]
    except IndexError as exc:
        raise RuntimeError('Receiver-exit cleanup result is not checked') from exc
    required_failure_order = (
        'g6_transport_failure_diag.transport_error_count = g6_transport_errors + 1U;',
        '++g6_transport_errors;',
        'mark_fault();',
        'return 1;')
    positions = [failed_cleanup.find(token) for token in required_failure_order]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        raise RuntimeError('Cleanup failure must be fatal and counted as transport error')
    if '++g6_disconnects;' in failed_cleanup:
        raise RuntimeError('Cleanup failure must not increment clean disconnect count')
    success = body.split('} else {', 1)[1]
    if 'phase = WAIT_HELLO;' not in success or '++g6_disconnects;' not in success:
        raise RuntimeError('Clean disconnect must retire the session and count only after cleanup')
    if 'g6_transport_failure_diag.send_status = send_status;' not in body:
        raise RuntimeError('Raw send failure status must be retained before cleanup')


def nm_symbols(nm, elf):
    result = subprocess.check_output([str(nm), '-S', str(elf)], text=True)
    return {f[3]: (int(f[0], 16), int(f[1], 16)) for line in result.splitlines()
            if len(f := line.split()) == 4}


def generate_candidate_usb(base_source, tail_source, output):
    source = base_source.read_text(encoding='utf-8')
    if source.count('g3_usb_capture') != 2:
        raise RuntimeError('Baseline G6 capture hook changed; refusing unreviewed patch')
    source = source.replace('#include "session.h"',
                            '#include "session.h"\n#include "g6_auto_recovery.h"', 1)
    source = source.replace('g3_usb_capture', 'g6_auto_capture_hook')
    hook_proto = 'int g6_auto_capture_hook(const uint8_t **data, unsigned *size);'
    if source.count(hook_proto) != 1:
        raise RuntimeError('Baseline G6 capture prototype changed')
    source = source.replace(hook_proto, 'static ' + hook_proto, 1)
    marker = 'volatile uint32_t g6_injected_capture_errors __attribute__((aligned(64)));'
    if source.count(marker) != 1:
        raise RuntimeError('Baseline G6 owned-ABI marker changed')
    source = source.replace(marker, marker +
        '\nvolatile uint32_t g6_auto_recovery_request __attribute__((aligned(64)));' +
        '\nvolatile struct g6_transport_failure_diag g6_transport_failure_diag ' +
        '__attribute__((aligned(64)));', 1)
    prototype = 'int usb_cdc_take_control(uint8_t *out, uint32_t capacity);'
    if source.count(prototype) != 1:
        raise RuntimeError('Baseline USB control API changed')
    source = source.replace(prototype,
        prototype + '\nint usb_cdc_clear_control_queue(void);\n'
        'int g6_candidate_recover_camera(void);', 1)
    if source.count(LOOP_OLD) != 1:
        raise RuntimeError('Baseline G6 capture-error branch changed; refusing unreviewed patch')
    source = source.replace(LOOP_OLD, LOOP_NEW, 1)
    if source.count(TRANSPORT_OLD) != 1:
        raise RuntimeError('Baseline G6 transport-error branch changed; refusing unreviewed patch')
    source = source.replace(TRANSPORT_OLD, TRANSPORT_NEW, 1)
    source += '\n' + tail_source.read_text(encoding='utf-8') + '\n'
    output.write_text(source, encoding='utf-8', newline='\n')
    return source


def generate_bounded_probe_unit(probe_source, wrapper_source, output):
    """Combine the generated probe and candidate helper in one translation unit.

    The baseline wrapper includes usb_probe.c; substitute only that include with
    the generated bounded overlay so candidate builds never link both variants.
    """
    wrapper = wrapper_source.read_text(encoding='utf-8')
    include = '#include "usb_probe.c"'
    if wrapper.count(include) != 1:
        raise RuntimeError('USB recovery wrapper include changed; refusing ambiguous probe build')
    generated = probe_source.read_text(encoding='utf-8')
    combined = wrapper.replace(include, generated, 1)
    output.write_text(combined, encoding='utf-8', newline='\n')
    return combined


def pin_bsp_inputs(bsp_workspace, workspace):
    """Snapshot the exact generated BSP headers and link inputs used by this build."""
    bsp_workspace = Path(bsp_workspace)
    source_cpu = bsp_workspace / 'bsp/ps7_cortexa9_0'
    if not source_cpu.is_dir():
        # Reuse the already pinned BSP copy from a completed candidate build.
        source_cpu = bsp_workspace / 'bsp_inputs/ps7_cortexa9_0'
    target_cpu = Path(workspace) / 'bsp_inputs/ps7_cortexa9_0'
    source_include = source_cpu / 'include'
    source_lib = source_cpu / 'lib'
    required = (source_include / 'xparameters.h', source_lib / 'libxil.a',
                source_lib / 'Xilinx.spec')
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError('Reused BSP is incomplete: ' + ', '.join(missing))
    target_cpu.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source_include, target_cpu / 'include')
    (target_cpu / 'lib').mkdir()
    for name in ('libxil.a', 'Xilinx.spec'):
        shutil.copy2(source_lib / name, target_cpu / 'lib' / name)
    inputs = {}
    for path in sorted((target_cpu / 'include').rglob('*')):
        if path.is_file():
            inputs[path.relative_to(workspace).as_posix()] = digest(path)
    for name in ('libxil.a', 'Xilinx.spec'):
        path = target_cpu / 'lib' / name
        inputs[path.relative_to(workspace).as_posix()] = digest(path)
    return target_cpu, inputs


def build_variant(workspace, xsa, tools, base_manifest, expected_g6_source_sha256,
                  bsp_workspace=None):
    bsp_workspace = Path(bsp_workspace or workspace).resolve()
    with zipfile.ZipFile(xsa) as archive:
        names = set(archive.namelist())
        if not {'m01.bit', 'ps7_init.tcl', 'system.hwh'} <= names:
            raise RuntimeError('Input XSA is missing bitstream, PS init, or system.hwh')
        if b'xc7z020clg400-2' not in archive.read('sysdef.xml'):
            raise RuntimeError('Expected the CF7020B xc7z020clg400-2 XSA')
        hwh = archive.read('system.hwh').decode('utf-8', 'replace')
        for ip in ('camera_0', 'dma_capture', 'dma_crypto', 'camera_gpio', 'dma_gpio', 'gcm_0'):
            if ip not in hwh:
                raise RuntimeError('XSA is missing G6 camera/DMA IP: ' + ip)

    base_data = json.loads(base_manifest.read_text(encoding='utf-8'))
    xsa_hash = digest(xsa)
    if base_data.get('xsa_sha256') != xsa_hash:
        raise RuntimeError('XSA does not match accepted usbfix3 G6 manifest')
    baseline_usb = ROOT / 'board/src/ps/src/g6_usb.c'
    source_text = baseline_usb.read_text(encoding='utf-8')
    verify_receiver_exit_cleanup_source(source_text)
    current_usb_sha256 = digest(baseline_usb)
    if current_usb_sha256 != expected_g6_source_sha256:
        raise RuntimeError('G6 security source differs from explicit expected SHA-256')
    source_baseline = dict(
        schema='eyepqc-derived-source-baseline-v1',
        derived_from=dict(manifest=str(base_manifest), sha256=digest(base_manifest),
                          accepted_g6_source_sha256=base_data.get('sources', {}).get(
                              'board/src/ps/src/g6_usb.c')),
        candidate_g6_source=dict(path='board/src/ps/src/g6_usb.c',
                                 sha256=current_usb_sha256),
        note='Candidate source is intentionally modified; this record binds the new source to the accepted baseline manifest without claiming source identity.')
    (workspace / 'source_baseline_manifest.json').write_text(
        json.dumps(source_baseline, indent=2) + '\n', encoding='utf-8')

    app = workspace / 'g6_usb'
    build = app / 'build'
    build.mkdir(parents=True, exist_ok=True)
    pinned_cpu, bsp_inputs = pin_bsp_inputs(bsp_workspace, workspace)
    # Candidate014 compiles the reviewed cleanup source directly. Its new hash
    # is explicit above and captured in source_baseline_manifest.json; it is not
    # passed off as the accepted pre-cleanup G6 source.
    candidate_usb = baseline_usb

    gcc = tools / 'Vitis/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    if not gcc.is_file():
        raise RuntimeError('ARM GCC is missing: ' + str(gcc))
    vendor = gcc.parents[5] / 'data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11/examples'
    sdk_root = vendor.parent
    sdk_generator = ROOT / 'board/prj/prepare_usb_bounded_sdk.py'
    sdk_overlay = workspace / 'usb_bounded_sdk/src'
    base.run([sys.executable, sdk_generator, '--source-root', sdk_root,
              '--out', workspace], ROOT, workspace / 'usb_bounded_sdk_generate.log')
    patched_endpoint = sdk_overlay / 'xusbps_endpoint.c'
    patched_ch9 = sdk_overlay / 'xusbps_ch9.c'
    patched_intr = sdk_overlay / 'xusbps_intr.c'
    candidate_probe = workspace / 'usb_probe_bounded_generated.c'
    candidate_probe_unit = workspace / 'usb_probe_auto_recovery_bounded_generated.c'
    generate_bounded_probe_unit(candidate_probe, ROOT / 'board/prj/usb_probe_auto_recovery.c',
                                candidate_probe_unit)
    sources = [ROOT / 'board/src/ps/diag/g3_camera_auto_recovery.c', candidate_usb,
               candidate_probe_unit,
               patched_endpoint, patched_ch9, patched_intr,
               *[ROOT / 'board/src/ps/src' / f for f in ('session.c', 'protocol.c', 'ephemeral.c', 'm09_mlkem.c')],
               *[ROOT / 'board/src/third_party/tinycrypt/lib/source' / f
                 for f in ('sha256.c', 'utils.c')]]
    include = [sdk_overlay, pinned_cpu / 'include', ROOT / 'board/src/ps/include',
               ROOT / 'board/src/third_party', ROOT / 'board/src/third_party/mlkem',
               ROOT / 'board/src/third_party/tinycrypt/lib/include', ROOT / "board/prj", vendor]
    for source in sources:
        if not source.is_file():
            raise RuntimeError('Build source missing: ' + str(source))
    flags = [*CPU_FLAGS, '-std=c11', '-O3', '-g', '-Wall', '-Wextra', '-Werror',
             '-DG4_USB', '-DUSB_LIBRARY', '-DG6_USB', '-DG6_SECURE_CLEANUP',
             '-DG6_AUTO_RECOVERY']
    include_flags = [arg for path in include for arg in ('-I', str(path))]
    objects, commands = [], []
    patched_endpoint_object = None
    patched_intr_object = None
    for index, source in enumerate(sources):
        obj = build / f'{index}_{source.stem}.o'
        command = [gcc, *flags, *include_flags, '-c', source, '-o', obj]
        base.run(command, ROOT, build / f'{index}_{source.stem}.log')
        commands.append(dict(directory=str(ROOT), file=str(source),
                             arguments=[str(arg) for arg in command]))
        objects.append(obj)
        if source.resolve() == patched_endpoint.resolve():
            patched_endpoint_object = obj
        if source.resolve() == patched_intr.resolve():
            patched_intr_object = obj

    cpu = pinned_cpu
    elf = build / 'g6_usb.elf'
    link = [gcc, *CPU_FLAGS, '-specs=' + str(cpu / 'lib/Xilinx.spec'),
            '-Wl,--defsym=_STACK_SIZE=0x8000', '-T', ROOT / 'board/prj/a9_ddr.ld',
            '-Wl,-Map=' + str(build / 'g6_usb.map'), '-L', cpu / 'lib',
            *objects, '-Wl,--start-group', '-lxil', '-lgcc', '-lc', '-Wl,--end-group', '-o', elf]
    base.run(link, ROOT, build / 'link.log')
    base.verify_startup(build / 'g6_usb.map')
    map_text = (build / 'g6_usb.map').read_text(encoding='utf-8', errors='replace')
    if not patched_endpoint_object or str(patched_endpoint_object) not in map_text:
        raise RuntimeError('Link map does not contain the isolated patched USB endpoint object')
    if not patched_intr_object or str(patched_intr_object) not in map_text:
        raise RuntimeError('Link map does not contain the isolated patched USB interrupt object')
    if 'libxil.a(usbps_v2_11_xusbps_endpoint.o)' in map_text:
        raise RuntimeError('Unpatched libxil USB endpoint object was also linked')
    if 'libxil.a(usbps_v2_11_xusbps_intr.o)' in map_text:
        raise RuntimeError('Unpatched libxil USB interrupt object was also linked')
    base.run([gcc.with_name('arm-none-eabi-readelf.exe'), '-h', elf], ROOT,
             build / 'elf_header.txt')
    abi = nm_symbols(gcc.with_name('arm-none-eabi-nm.exe'), elf)
    expected = {'g3_job': 128, 'g3_frame': 65600, 'g3_sealed': 68096,
                'g6_sk_load': 1632, 'g6_seed_load': 32, 'g6_ready': 4, 'g6_status': 4,
                'g6_frames': 4, 'g6_dropped': 4, 'g6_control_errors': 4,
                'g6_capture_errors': 4, 'g6_transport_errors': 4, 'g6_fatal_errors': 4,
                'g6_disconnects': 4, 'g6_fault_inject': 4,
                'g6_injected_capture_errors': 4, 'g6_auto_recovery_request': 4,
                'g6_auto_recovery_diag': 56,
                'g6_transport_failure_diag': 32, 'g6_secure_cleanup_diag': 120,
                'g6_rekey_diagnostic': 144}
    owned = {}
    for name, size in expected.items():
        address, actual = abi.get(name, (0, 0))
        if actual != size or address % 64 or not 0x100000 <= address <= 0x40000000 - size:
            raise RuntimeError(f'Invalid ELF-owned DDR ABI: {name}, {address:#x}, {actual}')
        owned[name] = dict(address=address, size=size)

    (app / '_ide/bitstream').mkdir(parents=True, exist_ok=True)
    (app / '_ide/psinit').mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(xsa) as archive:
        (app / '_ide/bitstream/m01.bit').write_bytes(archive.read('m01.bit'))
        (app / '_ide/psinit/ps7_init.tcl').write_bytes(archive.read('ps7_init.tcl'))
    (app / 'compile_commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')

    source_paths = [ROOT / 'board/src/ps/src/g3_camera.c', baseline_usb,
                    ROOT / 'board/src/ps/diag/g3_camera_auto_recovery.c',
                    ROOT / 'board/src/ps/diag/usb_bounded_sdk_policy.h',
                    ROOT / 'board/src/ps/diag/g6_usb_auto_recovery_tail.inc',
                    ROOT / 'board/prj/trigger_g6_auto_recovery.tcl',
                    ROOT / 'board/prj/read_g6_auto_health.tcl',
                    ROOT / 'board/prj/read_g6_rekey_diag.tcl',
                    ROOT / 'board/prj/capture_g6_rekey_diag.py',
                    ROOT / 'board/prj/run_g7_auto_recovery.py',
                    ROOT / 'run_g7_batch.ps1',
                    ROOT / 'sim/tb/test_g6_auto_recovery.py',
                    ROOT / 'sim/tb/test_g6_control_dispatch.py',
                    ROOT / 'sim/tb/test_g6_control_dispatch.c',
                    ROOT / 'sim/tb/test_g6_secure_cleanup.py',
                    ROOT / 'sim/tb/test_g6_secure_cleanup_harness.c',
                    ROOT / 'sim/tb/test_g6_cleanup_paths.py',
                    ROOT / 'sim/tb/test_g6_cleanup_paths.c',
                    ROOT / 'sim/tb/test_g6_usb_idle_fastpath.py',
                    ROOT / 'sim/tb/test_g6_usb_idle_fastpath.c',
                    ROOT / 'sim/tb/test_read_g6_rekey_diag_tcl.py',
                    ROOT / 'sim/tb/test_capture_g6_rekey_diag.py',
                    ROOT / 'sim/tb/test_g7_batch_hostsource.py',
                    ROOT / 'sim/tb/test_usb_bounded_sdk.py',
                    ROOT / 'sim/tb/test_usb_bounded_sdk_mock.c',
                    ROOT / 'sim/tb/test_usb_bounded_ch9_mock.c',
                    ROOT / 'sim/tb/test_usb_bounded_intr_mock.c',
                    ROOT / 'pc/src/host/g6_board.py', ROOT / 'pc/src/host/build_manifest.py',
                    ROOT / 'board/src/ps/include/g6_auto_recovery.h',
                    ROOT / 'board/src/ps/include/g6_secure_cleanup.h',
                    ROOT / 'board/src/ps/include/g6_rekey_diag.h',
                    ROOT / 'board/src/ps/include/g6_control_dispatch.h',
                    ROOT / 'board/src/ps/include/bsp_compat.h', ROOT / 'board/src/ps/include/session.h',
                    ROOT / 'board/src/ps/include/protocol.h', ROOT / 'board/src/ps/include/usb_recovery.h',
                    ROOT / 'board/src/ps/include/mvp_gcm.h', ROOT / 'board/src/ps/include/dma_buffers.h',
                    ROOT / 'board/src/ps/src/session.c', ROOT / 'board/src/ps/src/protocol.c',
                    ROOT / 'board/src/ps/src/m09_mlkem.c', ROOT / 'board/src/ps/src/ephemeral.c',
                    ROOT / 'board/src/ps/include/ephemeral.h', ROOT / 'board/prj/usb_probe_auto_recovery.c',
                    ROOT / 'board/prj/usb_probe.c', candidate_probe, candidate_probe_unit, ROOT / 'board/prj/a9_ddr.ld',
                    ROOT / 'board/prj/prepare_usb_bounded_sdk.py',
                    ROOT / 'board/prj/build_g6_auto_recovery.py', ROOT / 'board/prj/build_software.py',
                    ROOT / 'board/prj/generate_bsp.tcl', candidate_usb]
    source_paths += sorted((ROOT / 'board/src/third_party/mlkem').rglob('*'))
    source_paths += sorted((ROOT / 'board/src/third_party/tinycrypt/lib/include').rglob('*.h'))
    source_paths += sorted((ROOT / 'board/src/third_party/tinycrypt/lib/source').glob('*.c'))
    sources_hash = {path.relative_to(ROOT).as_posix(): digest(path)
                    for path in source_paths if path.is_file() and ROOT in path.parents}
    sdk_src_relative = (sdk_root / 'src/xusbps_endpoint.c').relative_to(tools).as_posix()
    sdk_ch9_relative = (sdk_root / 'examples/xusbps_ch9.c').relative_to(tools).as_posix()
    sdk_intr_relative = (sdk_root / 'src/xusbps_intr.c').relative_to(tools).as_posix()
    sdk_ch9_header_relative = (sdk_root / 'examples/xusbps_ch9.h').relative_to(tools).as_posix()
    gcc_relative = gcc.resolve().relative_to(tools.resolve()).as_posix()
    external_sources = {sdk_src_relative: digest(sdk_root / 'src/xusbps_endpoint.c'),
                        sdk_ch9_relative: digest(sdk_root / 'examples/xusbps_ch9.c'),
                        sdk_intr_relative: digest(sdk_root / 'src/xusbps_intr.c'),
                        sdk_ch9_header_relative: digest(sdk_root / 'examples/xusbps_ch9.h'),
                        gcc_relative: digest(gcc)}
    manifest = dict(application='g6_usb', variant=VARIANT,
                    base_application='g6_usb', base_manifest=str(base_manifest),
                    base_manifest_sha256=digest(base_manifest), xsa=str(xsa),
                    xsa_sha256=xsa_hash,
                    patch_id=VARIANT,
                    trigger_modes={'1': 'PL camera reset/PWDN before normal S2MM capture',
                                   '2': 'PL capture route mode 3 disables all valid/ready before S2MM capture'},
                    sources=sources_hash, external_sources=external_sources,
                    external_sources_root='tool-root', bsp_inputs=bsp_inputs,
                    bsp_inputs_origin=str(bsp_workspace.resolve() / 'bsp/ps7_cortexa9_0'),
                    toolchain=dict(gcc_version=subprocess.check_output(
                        [str(gcc), '--version'], text=True).splitlines()[0],
                        gcc_relative_path=gcc_relative),
                    owned=owned, board_validated=False,
                    source_baseline_manifest={
                        'path': 'source_baseline_manifest.json',
                        'sha256': digest(workspace / 'source_baseline_manifest.json')},
                    artifacts={p.relative_to(workspace).as_posix(): digest(p) for p in
                               (elf, build / 'g6_usb.map', app / '_ide/bitstream/m01.bit',
                                app / '_ide/psinit/ps7_init.tcl',
                                app / 'compile_commands.json',
                                workspace / 'usb_bounded_sdk_generate.log',
                                 sdk_overlay / 'xusbps_endpoint.c',
                                 sdk_overlay / 'xusbps_ch9.c',
                                 sdk_overlay / 'xusbps_intr.c',
                                 sdk_overlay / 'usb_bounded_sdk_policy.h',
                                 workspace / 'usb_probe_bounded_generated.c',
                                workspace / 'usb_probe_auto_recovery_bounded_generated.c',
                                workspace / 'source_baseline_manifest.json',
                                workspace / 'usb_bounded_sdk/manifest.json')})
    text = json.dumps(manifest, indent=2) + '\n'
    (workspace / 'build_manifest.json').write_text(text, encoding='utf-8')
    (workspace / 'g6_usb_manifest.json').write_text(text, encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xsa', type=Path, default=ROOT / 'build/vivado/g3_gui/m01.xsa')
    parser.add_argument('--base-manifest', type=Path,
                        default=ROOT / 'build/vitis/usbfix3_20261007/g6_usb_manifest.json')
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'build/vitis/g6_secure_cleanup_20261011_candidate014_safe_hello_ack_retry')
    parser.add_argument('--reuse-bsp', type=Path, default=None,
                        help='reuse an existing same-XSA BSP workspace without regenerating it')
    parser.add_argument('--expected-g6-source-sha256', required=True,
                        help='explicit SHA-256 of the modified G6 source for a derived candidate')
    parser.add_argument('--tool-root', type=Path, default=Path('E:/fpg/2026.1'))
    args = parser.parse_args()
    xsa, base_manifest, workspace, tools = (p.resolve() for p in
        (args.xsa, args.base_manifest, args.output, args.tool_root))
    if not xsa.is_file() or not base_manifest.is_file() or workspace.exists():
        parser.error('XSA and matching baseline manifest must exist, and output must be fresh')
    workspace.mkdir(parents=True)
    bsp_workspace = args.reuse_bsp.resolve() if args.reuse_bsp else workspace
    if args.reuse_bsp:
        prior_manifest = bsp_workspace / 'g6_usb_manifest.json'
        has_bsp = ((bsp_workspace / 'bsp/ps7_cortexa9_0/include/xparameters.h').is_file() or
                   (bsp_workspace / 'bsp_inputs/ps7_cortexa9_0/include/xparameters.h').is_file())
        if not has_bsp or \
                not prior_manifest.is_file():
            parser.error('--reuse-bsp must name a prior G6 workspace with a complete pinned BSP')
        prior = json.loads(prior_manifest.read_text(encoding='utf-8'))
        if prior.get('xsa_sha256') != digest(xsa):
            parser.error('--reuse-bsp XSA hash differs from requested XSA')
    else:
        base.build_bsp(workspace, xsa, tools, boot_images=False)
    manifest = build_variant(workspace, xsa, tools, base_manifest,
                             args.expected_g6_source_sha256,
                             bsp_workspace=bsp_workspace)
    print('G6_AUTO_RECOVERY_BUILD_OK', workspace, manifest['xsa_sha256'], flush=True)


if __name__ == '__main__':
    main()
