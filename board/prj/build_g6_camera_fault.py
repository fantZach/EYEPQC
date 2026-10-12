"""Build an isolated, JTAG-only G6 camera-reset/DMA-stall diagnostic variant."""
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


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def nm_symbols(nm, elf):
    result = subprocess.check_output([str(nm), '-S', str(elf)], text=True)
    return {f[3]: (int(f[0], 16), int(f[1], 16)) for line in result.splitlines()
            if len(f := line.split()) == 4}


def build_variant(workspace, xsa, tools, base_manifest):
    with zipfile.ZipFile(xsa) as archive:
        names = set(archive.namelist())
        if not {'m01.bit', 'ps7_init.tcl', 'system.hwh'} <= names:
            raise RuntimeError('Input XSA is missing bitstream, PS init, or system.hwh')
        if archive.read('sysdef.xml').find(b'xc7z020clg400-2') < 0:
            raise RuntimeError('Expected the CF7020B xc7z020clg400-2 XSA')
        hwh = archive.read('system.hwh').decode('utf-8', 'replace')
        for ip in ('camera_0', 'dma_capture', 'dma_crypto', 'camera_gpio', 'dma_gpio'):
            if ip not in hwh:
                raise RuntimeError('XSA is missing G6 camera/DMA IP: ' + ip)

    base_data = json.loads(base_manifest.read_text(encoding='utf-8'))
    xsa_hash = digest(xsa)
    if base_data.get('xsa_sha256') != xsa_hash:
        raise RuntimeError('XSA does not match the accepted usbfix3 G6 manifest')

    # Match the ordinary G6 workspace ABI so existing JTAG/provision tooling can
    # load this separate variant without edits to the baseline scripts.
    app = workspace / 'g6_usb'
    build = app / 'build'
    build.mkdir(parents=True)
    gcc = tools / 'Vitis/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    if not gcc.is_file():
        raise RuntimeError('ARM GCC is missing: ' + str(gcc))
    vendor = gcc.parents[5] / 'data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11/examples'
    sources = [ROOT / 'board/src/ps/diag/g3_camera_fault_diag.c',
               ROOT / 'board/src/ps/diag/g6_usb_camera_fault.c',
               ROOT / 'board/prj/usb_probe.c', vendor / 'xusbps_ch9.c',
               *[ROOT / 'board/src/ps/src' / f for f in ('session.c', 'protocol.c', 'm09_mlkem.c')],
               *[ROOT / 'board/src/third_party/tinycrypt/lib/source' / f for f in ('sha256.c', 'utils.c')]]
    include = [workspace / 'bsp/ps7_cortexa9_0/include', ROOT / 'board/src/ps/include',
               ROOT / 'board/src/third_party', ROOT / 'board/src/third_party/mlkem',
               ROOT / 'board/src/third_party/tinycrypt/lib/include', vendor]
    for source in sources:
        if not source.is_file():
            raise RuntimeError('Build source missing: ' + str(source))
    flags = [*CPU_FLAGS, '-std=c11', '-O3', '-g', '-Wall', '-Wextra', '-Werror',
             '-DG4_USB', '-DUSB_LIBRARY', '-DG6_USB']
    include_flags = [arg for path in include for arg in ('-I', str(path))]
    objects = []
    commands = []
    for index, source in enumerate(sources):
        obj = build / f'{index}_{source.stem}.o'
        command = [gcc, *flags, *include_flags, '-c', source, '-o', obj]
        base.run(command, ROOT, build / f'{index}_{source.stem}.log')
        commands.append(dict(directory=str(ROOT), file=str(source),
                             arguments=[str(arg) for arg in command]))
        objects.append(obj)

    cpu = workspace / 'bsp/ps7_cortexa9_0'
    elf = build / 'g6_usb.elf'
    link = [gcc, *CPU_FLAGS, '-specs=' + str(cpu / 'lib/Xilinx.spec'),
            '-Wl,--defsym=_STACK_SIZE=0x8000', '-T', ROOT / 'board/prj/a9_ddr.ld',
            '-Wl,-Map=' + str(build / 'g6_usb.map'), '-L', cpu / 'lib',
            *objects, '-Wl,--start-group', '-lxil', '-lgcc', '-lc', '-Wl,--end-group', '-o', elf]
    base.run(link, ROOT, build / 'link.log')
    base.verify_startup(build / 'g6_usb.map')
    base.run([gcc.with_name('arm-none-eabi-readelf.exe'), '-h', elf], ROOT,
             build / 'elf_header.txt')
    abi = nm_symbols(gcc.with_name('arm-none-eabi-nm.exe'), elf)
    expected = {'g3_job': 128, 'g3_frame': 65600, 'g3_sealed': 68096,
                'g6_sk_load': 1632, 'g6_seed_load': 32, 'g6_ready': 4, 'g6_status': 4,
                'g6_frames': 4, 'g6_dropped': 4, 'g6_control_errors': 4,
                'g6_capture_errors': 4, 'g6_transport_errors': 4, 'g6_fatal_errors': 4,
                'g6_disconnects': 4, 'g6_fault_inject': 4,
                'g6_injected_capture_errors': 4, 'g6_camera_fault_inject': 4,
                'g6_camera_fault_diag': 56}
    owned = {}
    for name, size in expected.items():
        address, actual = abi.get(name, (0, 0))
        if actual != size or address % 64 or not 0x100000 <= address <= 0x40000000 - size:
            raise RuntimeError(f'Invalid ELF-owned DDR ABI: {name}, {address:#x}, {actual}')
        owned[name] = dict(address=address, size=size)

    app.joinpath('_ide/bitstream').mkdir(parents=True)
    app.joinpath('_ide/psinit').mkdir(parents=True)
    with zipfile.ZipFile(xsa) as archive:
        (app / '_ide/bitstream/m01.bit').write_bytes(archive.read('m01.bit'))
        (app / '_ide/psinit/ps7_init.tcl').write_bytes(archive.read('ps7_init.tcl'))
    (app / 'compile_commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')

    inputs = [ROOT / 'board/src/ps/src/g3_camera.c', ROOT / 'board/src/ps/src/g6_usb.c',
              ROOT / 'board/src/ps/diag/g3_camera_fault_diag.c',
              ROOT / 'board/src/ps/diag/g6_usb_camera_fault.c',
              ROOT / 'board/src/ps/include/g6_camera_fault_diag.h',
              ROOT / 'board/src/ps/include/bsp_compat.h', ROOT / 'board/src/ps/include/session.h',
              ROOT / 'board/src/ps/include/protocol.h', ROOT / 'board/src/ps/include/usb_recovery.h',
              ROOT / 'board/src/ps/include/mvp_gcm.h', ROOT / 'board/src/ps/include/dma_buffers.h',
              ROOT / 'board/src/ps/src/session.c', ROOT / 'board/src/ps/src/protocol.c',
              ROOT / 'board/src/ps/src/m09_mlkem.c', ROOT / 'board/prj/usb_probe.c',
              ROOT / 'board/prj/a9_ddr.ld', ROOT / 'board/prj/build_g6_camera_fault.py',
              ROOT / 'board/prj/build_software.py', ROOT / 'board/prj/generate_bsp.tcl',
              ROOT / 'board/prj/trigger_g6_camera_fault.tcl',
              ROOT / 'board/prj/run_g7_camera_reset_dma.py',
              ROOT / 'sim/tb/test_g7_camera_reset_dma.py']
    inputs += sorted((ROOT / 'board/src/third_party/mlkem').rglob('*'))
    inputs += sorted((ROOT / 'board/src/third_party/tinycrypt/lib/include').rglob('*.h'))
    inputs += sorted((ROOT / 'board/src/third_party/tinycrypt/lib/source').glob('*.c'))
    source_hashes = {path.relative_to(ROOT).as_posix(): digest(path)
                     for path in inputs if path.is_file()}
    manifest = dict(application='g6_usb', variant='controlled-camera-reset-real-dma-stall',
                    base_application='g6_usb', base_manifest=str(base_manifest),
                    base_manifest_sha256=digest(base_manifest),
                    xsa=str(xsa), xsa_sha256=xsa_hash, sources=source_hashes, owned=owned,
                    board_validated=False,
                    artifacts={p.relative_to(workspace).as_posix(): digest(p) for p in
                               (elf, build / 'g6_usb.map',
                                app / '_ide/bitstream/m01.bit', app / '_ide/psinit/ps7_init.tcl')})
    text = json.dumps(manifest, indent=2) + '\n'
    (workspace / 'build_manifest.json').write_text(text, encoding='utf-8')
    (workspace / 'g6_usb_manifest.json').write_text(text, encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xsa', type=Path, default=ROOT / 'build/vivado/g3_gui/m01.xsa')
    parser.add_argument('--base-manifest', type=Path,
                        default=ROOT / 'build/vitis/usbfix3_20261007/g6_usb_manifest.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/vitis/g6_camera_fault_20261008')
    parser.add_argument('--tool-root', type=Path, default=Path('E:/fpg/2026.1'))
    args = parser.parse_args()
    xsa, base_manifest, workspace, tools = (p.resolve() for p in
        (args.xsa, args.base_manifest, args.output, args.tool_root))
    if not xsa.is_file() or not base_manifest.is_file() or workspace.exists():
        parser.error('XSA and matching baseline manifest must exist, and output must be fresh')
    workspace.mkdir(parents=True)
    cpu, _ = base.build_bsp(workspace, xsa, tools, boot_images=False)
    manifest = build_variant(workspace, xsa, tools, base_manifest)
    print('G6_CAMERA_FAULT_BUILD_OK', workspace, manifest['xsa_sha256'], flush=True)


if __name__ == '__main__':
    main()
