"""Offline classic HSI/ARM GCC build of G3 and G4/G5/G6 from one completed XSA.

Does not start a hardware server, connect to JTAG, or write boot media.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from arm_startup import verify_startup

ROOT = Path(__file__).resolve().parents[1]
CPU_FLAGS = ['-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard']
APP_NAMES = ('g3_camera', 'g4_usb', 'g5_usb', 'g6_usb')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, cwd, log):
    result = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True,
                            text=True, errors='replace', timeout=300)
    Path(log).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}); see {log}')
    return result.stdout + result.stderr


def build_bsp(workspace, xsa, tools, boot_images=False):
    output = workspace / 'bsp'
    log = workspace / 'bsp_generate.log'
    text = run([tools / 'Vivado/bin/xsdb.bat', ROOT / 'prj/generate_bsp.tcl',
                xsa, output, tools / 'Vitis/data/embeddedsw',
                *(['fsbl'] if boot_images else [])], ROOT, log)
    if 'EYEPQC_BSP_GENERATED' not in text:
        raise RuntimeError(f'BSP generation did not complete; see {log}')
    cpu = output / 'ps7_cortexa9_0'
    include = cpu / 'include'
    libsrc = cpu / 'libsrc'
    sources = []
    for directory in sorted(libsrc.glob('*/src')):
        for header in directory.glob('*.h'):
            target = include / header.name
            if target.exists() and target.read_bytes() != header.read_bytes():
                raise RuntimeError(f'Conflicting BSP header: {header.name}')
            shutil.copy2(header, target)
        sources.extend(sorted(directory.glob('*.c')))
        sources.extend(sorted(directory.glob('*.S')))
    gcc = tools / 'Vitis/gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    ar = gcc.with_name('arm-none-eabi-ar.exe')
    objects = workspace / 'bsp_objects'
    objects.mkdir()

    def compile_source(source):
        stem = source.parent.parent.name + '_' + source.stem
        obj = objects / (stem + '.o')
        run([gcc, *CPU_FLAGS, '-O2', '-g', '-Wall', '-Wextra',
             '-fno-tree-loop-distribute-patterns', '-I', include,
             '-I', source.parent, '-c', source, '-o', obj], source.parent,
            objects / (stem + '.log'))
        return obj

    with ThreadPoolExecutor(max_workers=4) as pool:
        compiled = list(pool.map(compile_source, sources))
    library = cpu / 'lib/libxil.a'
    library.parent.mkdir(exist_ok=True)
    # AMD's startfile spec keeps crti/crtbegin but excludes generic newlib crt0.
    # This makes _start resolve to the standalone BSP's xil-crt0.S.
    shutil.copy2(tools / 'Vitis/data/embeddedsw/scripts/specs/arm/Xilinx.spec',
                 library.parent / 'Xilinx.spec')
    response = workspace / 'bsp_archive.args'
    response.write_text('\n'.join('"' + p.as_posix() + '"' for p in compiled), encoding='utf-8')
    run([ar, 'rcs', library, '@' + str(response)], ROOT, workspace / 'bsp_archive.log')
    print(f'BSP_BUILD_OK sources={len(compiled)}', flush=True)
    return cpu, gcc


def build_boot_images(workspace, cpu, gcc, tools, apps, xsa):
    fsbl = workspace / 'fsbl'
    sources = sorted(fsbl.glob('*.c')) + sorted(fsbl.glob('*.S'))
    if not sources or not (fsbl / 'ps7_init.c').is_file():
        raise RuntimeError('HSI did not generate FSBL sources and matching ps7_init')
    with zipfile.ZipFile(xsa) as archive:
        for name in ('ps7_init.c', 'ps7_init.h'):
            if archive.read(name) != (fsbl / name).read_bytes():
                raise RuntimeError('FSBL PS initialization differs from input XSA: ' + name)
    build = fsbl / 'build'
    build.mkdir()
    objects = []
    for index, source in enumerate(sources):
        obj = build / f'{index}_{source.stem}.o'
        run([gcc, *CPU_FLAGS, '-Os', '-ffunction-sections', '-fdata-sections',
             '-DFSBL_DEBUG_INFO', '-I', cpu / 'include', '-I', fsbl, '-c', source, '-o', obj],
            ROOT, build / (source.stem + '.log'))
        objects.append(obj)
    elf = build / 'fsbl.elf'
    run([gcc, *CPU_FLAGS, '-specs=' + str(cpu / 'lib/Xilinx.spec'),
         '-Wl,--gc-sections', '-T', fsbl / 'lscript.ld',
         '-L', cpu / 'lib', *objects, '-Wl,--start-group', '-lxil', '-lgcc', '-lc',
         '-Wl,--end-group', '-Wl,-Map=' + str(build / 'fsbl.map'), '-o', elf],
        ROOT, build / 'link.log')
    verify_startup(build / 'fsbl.map')
    run([gcc.with_name('arm-none-eabi-readelf.exe'), '-h', '-l', elf], ROOT, build / 'elf_header.txt')
    bootgen = tools / 'Vivado/bin/bootgen.bat'
    for name in apps:
        output = workspace / name / 'boot'
        output.mkdir()
        bif = output / 'boot.bif'
        bif.write_text('the_ROM_image:\n{\n    [bootloader] "' + elf.as_posix() +
                       '"\n    "' + (workspace / name / '_ide/bitstream/m01.bit').as_posix() +
                       '"\n    "' + (workspace / name / 'build' / (name + '.elf')).as_posix() +
                       '"\n}\n', encoding='utf-8')
        run([bootgen, '-arch', 'zynq', '-image', bif, '-o', output / 'BOOT.BIN'],
            ROOT, output / 'bootgen.log')
        run([bootgen, '-arch', 'zynq', '-read', output / 'BOOT.BIN'],
            ROOT, output / 'bootgen_read.txt')
        print('BOOT_IMAGE_OK', name, flush=True)
    return elf


def symbols(nm, elf):
    output = subprocess.check_output([str(nm), '-S', str(elf)], text=True)
    return {f[3]: (int(f[0], 16), int(f[1], 16)) for line in output.splitlines()
            if len(f := line.split()) == 4}


def build_app(name, workspace, cpu, gcc, xsa, production_provider=None):
    app = workspace / name
    build = app / 'build'
    build.mkdir(parents=True)
    defines = [] if name == 'g3_camera' else ['G4_USB', 'USB_LIBRARY']
    if name == 'g5_usb':
        defines.append('G5_USB')
    if name == 'g6_usb':
        defines.append('G6_USB')
        if production_provider is not None:
            defines.append('G6_PRODUCTION')
    sources = [ROOT / 'src/ps/src/g3_camera.c']
    include = [cpu / 'include', ROOT / 'src/ps/include']
    if name != 'g3_camera':
        # HSI generates driver sources; official examples stay in the install.
        vendor = gcc.parents[5] / 'data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11/examples'
        sources += [ROOT / 'src/ps/src' / ('g6_usb.c' if name == 'g6_usb' else 'g4_usb.c'),
                    ROOT / 'prj/usb_probe.c', vendor / 'xusbps_ch9.c']
        include += [vendor]
    if name == 'g6_usb':
        sources += [ROOT / 'src/ps/src' / f for f in
                    ('session.c', 'protocol.c', 'm09_mlkem.c', 'g6_hmac_drbg.c')]
        sources += [ROOT / 'src/third_party/tinycrypt/lib/source' / f for f in ('sha256.c', 'utils.c')]
        if production_provider is not None:
            sources.append(production_provider)
        include += [ROOT / 'src/third_party', ROOT / 'src/third_party/mlkem',
                    ROOT / 'src/third_party/tinycrypt/lib/include']
    linker = ROOT / 'prj/a9_ddr.ld'
    inputs = [p for p in sources if p.is_relative_to(ROOT)] + [linker, ROOT / 'src/ps/include/bsp_compat.h']
    if name != 'g3_camera':
        inputs.append(ROOT / 'src/ps/include/usb_recovery.h')
    if name == 'g6_usb':
        inputs += list((ROOT / 'src/ps/include').glob('*.h'))
        inputs += list((ROOT / 'src/third_party/mlkem').rglob('*'))
        inputs += list((ROOT / 'src/third_party/tinycrypt/lib/include').rglob('*.h'))
    hashes = {p.relative_to(ROOT).as_posix(): digest(p) for p in inputs if p.is_file()}
    provider_hash = digest(production_provider) if production_provider is not None else None
    flags = [*CPU_FLAGS, '-std=c11', '-O3', '-g', '-Wall', '-Wextra', '-Werror',
             *['-D' + d for d in defines]]
    include_flags = [a for path in include for a in ('-I', str(path))]
    commands, objects = [], []
    for index, source in enumerate(sources):
        obj = build / f'{index}_{source.stem}.o'
        args = [gcc, *flags, *include_flags, '-c', source, '-o', obj]
        run(args, ROOT, build / f'{index}_{source.stem}.log')
        commands.append(dict(directory=str(ROOT), file=str(source), arguments=[str(a) for a in args]))
        objects.append(obj)
    elf = build / (name + '.elf')
    link = [gcc, *CPU_FLAGS, '-specs=' + str(cpu / 'lib/Xilinx.spec'),
            '-Wl,--defsym=_STACK_SIZE=0x8000' if name == 'g6_usb'
            else '-Wl,--defsym=_STACK_SIZE=0x2000', '-T', linker,
            '-Wl,-Map=' + str(build / (name + '.map')), '-L', cpu / 'lib',
            *objects, '-Wl,--start-group', '-lxil', '-lgcc', '-lc', '-Wl,--end-group', '-o', elf]
    run(link, ROOT, build / 'link.log')
    verify_startup(build / (name + '.map'))
    (build / 'link_command.json').write_text(json.dumps([str(a) for a in link], indent=2) + '\n', encoding='utf-8')
    run([gcc.with_name('arm-none-eabi-readelf.exe'), '-h', elf], ROOT, build / 'elf_header.txt')
    abi = symbols(gcc.with_name('arm-none-eabi-nm.exe'), elf)
    expected = {'g3_job': 128, 'g3_frame': 65600, 'g3_sealed': 68096}
    if name == 'g6_usb':
        if production_provider is None:
            expected.update(g6_sk_load=1632, g6_seed_load=32, g6_ready=4)
        expected.update(g6_status=4)
        expected.update(g6_frames=4, g6_dropped=4, g6_control_errors=4,
                        g6_capture_errors=4, g6_transport_errors=4,
                        g6_fatal_errors=4, g6_disconnects=4,
                        g6_fault_inject=4, g6_injected_capture_errors=4)
    owned = {}
    for key, size in expected.items():
        address, actual = abi.get(key, (0, 0))
        if actual != size or address % 64 or not 0x100000 <= address <= 0x40000000 - size:
            raise RuntimeError(f'Invalid ELF-owned DDR ABI: {name}/{key}')
        owned[key] = dict(address=address, size=size)
    with zipfile.ZipFile(xsa) as archive:
        for member, target in [('m01.bit', app / '_ide/bitstream/m01.bit'),
                               ('ps7_init.tcl', app / '_ide/psinit/ps7_init.tcl')]:
            target.parent.mkdir(parents=True)
            target.write_bytes(archive.read(member))
    (app / 'compile_commands.json').write_text(json.dumps(commands, indent=2) + '\n', encoding='utf-8')
    for relative, expected in hashes.items():
        if digest(ROOT / relative) != expected:
            raise RuntimeError('Source changed during compilation: ' + relative)
    if production_provider is not None and digest(production_provider) != provider_hash:
        raise RuntimeError('Production provider changed during compilation')
    manifest = dict(xsa=str(xsa), xsa_sha256=digest(xsa), application=name,
                    bsp_sha256=digest(cpu / 'lib/libxil.a'),
                    sources=hashes,
                    owned=owned, board_validated=False,
                    artifacts={p.relative_to(workspace).as_posix(): digest(p) for p in
                               (elf, build / (name + '.map'), app / '_ide/bitstream/m01.bit', app / '_ide/psinit/ps7_init.tcl')})
    if name == 'g6_usb':
        manifest['security_profile'] = ('external_provider_unvalidated' if production_provider is not None
                                        else 'development_jtag_mailbox')
        manifest['development_provisioning_required'] = production_provider is None
        if production_provider is not None:
            manifest['production_provider'] = dict(
                path=production_provider.relative_to(workspace).as_posix(),
                sha256=provider_hash)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xsa', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Fresh output directory')
    parser.add_argument('--tool-root', type=Path, default=os.environ.get('EYEPQC_TOOL_ROOT', 'E:/fpg/2026.1'))
    parser.add_argument('--apps', nargs='+', choices=APP_NAMES, default=list(APP_NAMES))
    parser.add_argument('--boot-images', action='store_true', help='Build matching FSBL/BOOT.BIN files; never write media')
    parser.add_argument('--g6-production-provider', type=Path,
                        help='Compile an explicit G6_PRODUCTION provider source; its quality is not security-certified')
    args = parser.parse_args()
    xsa, workspace, tools = args.xsa.resolve(), args.output.resolve(), args.tool_root.resolve()
    provider_source = args.g6_production_provider.resolve() if args.g6_production_provider else None
    if provider_source is not None and 'g6_usb' not in args.apps:
        parser.error('--g6-production-provider requires --apps to include g6_usb')
    if provider_source is not None and not provider_source.is_file():
        parser.error('G6 production provider source does not exist')
    if not xsa.is_file() or workspace.exists():
        parser.error('Completed XSA and fresh output directory required')
    with zipfile.ZipFile(xsa) as archive:
        xml = ET.fromstring(archive.read('sysdef.xml'))
        if xml.find('SYSTEMINFO').attrib.get('PART') != 'xc7z020clg400-2':
            parser.error('Expected xc7z020clg400-2 XSA')
        if not {'m01.bit', 'ps7_init.tcl'} <= set(archive.namelist()):
            parser.error('XSA must contain bitstream and PS initialization')
    workspace.mkdir(parents=True)
    provider_for_build = None
    if provider_source is not None:
        provider_dir = workspace / '_production_provider'
        provider_dir.mkdir()
        provider_for_build = provider_dir / 'g6_production_provider.c'
        shutil.copy2(provider_source, provider_for_build)
        if digest(provider_for_build) != digest(provider_source):
            raise RuntimeError('Copied G6 production provider does not match the requested source')
    xsa_hash = digest(xsa)
    cpu, gcc = build_bsp(workspace, xsa, tools, args.boot_images)
    manifests = {}
    for name in args.apps:
        manifests[name] = build_app(name, workspace, cpu, gcc, xsa,
                                    provider_for_build if name == 'g6_usb' else None)
        (workspace / (name + '_manifest.json')).write_text(json.dumps(manifests[name], indent=2) + '\n', encoding='utf-8')
        print('ARM_ELF_OK', name, flush=True)
    if args.boot_images:
        fsbl = build_boot_images(workspace, cpu, gcc, tools, manifests, xsa)
        for name, manifest in manifests.items():
            for path in (fsbl, fsbl.with_suffix('.map'), workspace / name / 'boot/BOOT.BIN'):
                manifest['artifacts'][path.relative_to(workspace).as_posix()] = digest(path)
            manifest['development_provisioning_required'] = (
                manifest.get('security_profile') == 'development_jtag_mailbox')
            (workspace / (name + '_manifest.json')).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    if 'g3_camera' in manifests:
        (workspace / 'build_manifest.json').write_text(json.dumps(manifests['g3_camera'], indent=2) + '\n', encoding='utf-8')
    if digest(xsa) != xsa_hash:
        raise RuntimeError('Input XSA changed during build')
    build_inputs = {p.relative_to(workspace).as_posix(): digest(p)
                    for p in (workspace / 'bsp').rglob('*')
                    if p.is_file() and p.suffix in ('.h', '.c', '.S', '.mss', '.spec')}
    build_inputs.update({p.relative_to(workspace).as_posix(): digest(p)
                         for p in (workspace / 'fsbl').glob('*')
                         if p.is_file() and p.suffix in ('.h', '.c', '.S', '.ld')})
    build_inputs.update({p.relative_to(workspace).as_posix(): digest(p)
                         for p in workspace.glob('*/compile_commands.json')})
    build_inputs.update({p.relative_to(workspace).as_posix(): digest(p)
                         for p in workspace.glob('*/build/link_command.json')})
    if provider_for_build is not None:
        build_inputs[provider_for_build.relative_to(workspace).as_posix()] = digest(provider_for_build)
    (workspace / 'software_build.json').write_text(json.dumps(dict(
        xsa_sha256=xsa_hash, tool_root=str(tools), applications=list(manifests),
        generated_inputs=build_inputs,
        build_scripts={p.relative_to(ROOT).as_posix(): digest(p) for p in
                       (ROOT / 'prj/build_software.py', ROOT / 'prj/generate_bsp.tcl',
                        ROOT / 'prj/arm_startup.py')},
        build_method='classic_hsi_arm_gcc', boot_images=args.boot_images,
        board_validated=False), indent=2) + '\n', encoding='utf-8')
    print('SOFTWARE_BUILD_OK', workspace, flush=True)


if __name__ == '__main__':
    main()
