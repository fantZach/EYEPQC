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
import sys
import zipfile
import xml.etree.ElementTree as ET
from arm_startup import verify_startup

ROOT = Path(__file__).resolve().parents[2]
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


def build_bsp(workspace, xsa, tools, boot_images=False, sd_identity=False):
    output = workspace / 'bsp'
    log = workspace / 'bsp_generate.log'
    text = run([tools / 'Vivado/bin/xsdb.bat', ROOT / 'board/prj/generate_bsp.tcl',
                xsa, output, tools / 'Vitis/data/embeddedsw',
                *(['fsbl'] if boot_images else ['sd'] if sd_identity else [])], ROOT, log)
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


def prepare_secure_cleanup_usb(workspace, gcc):
    """Generate the hash-pinned bounded USBPS overlay for ordered G6 cleanup."""
    vendor = gcc.parents[5] / 'data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11/examples'
    sdk_root = vendor.parent
    run([sys.executable, ROOT / 'board/prj/prepare_usb_bounded_sdk.py',
         '--source-root', sdk_root, '--out', workspace], ROOT,
        workspace / 'usb_bounded_sdk_generate.log')

    overlay = workspace / 'usb_bounded_sdk/src'
    generated_probe = workspace / 'usb_probe_bounded_generated.c'
    wrapper_source = ROOT / 'board/prj/usb_probe_auto_recovery.c'
    wrapper = wrapper_source.read_text(encoding='utf-8')
    include = '#include "usb_probe.c"'
    if wrapper.count(include) != 1:
        raise RuntimeError('Secure USB cleanup wrapper include changed')
    wrapper = wrapper.replace(include,
                              generated_probe.read_text(encoding='utf-8'), 1)
    wrapper_unit = workspace / 'usb_probe_secure_cleanup_bounded_generated.c'
    wrapper_unit.write_text(wrapper, encoding='utf-8', newline='\n')

    generated = [overlay / name for name in
                 ('xusbps_endpoint.c', 'xusbps_ch9.c', 'xusbps_intr.c')]
    generated += [generated_probe, wrapper_unit]
    if any(not path.is_file() for path in generated):
        raise RuntimeError('Secure USB cleanup overlay generation was incomplete')
    external_sources = {
        'src/xusbps_endpoint.c': digest(sdk_root / 'src/xusbps_endpoint.c'),
        'examples/xusbps_ch9.c': digest(sdk_root / 'examples/xusbps_ch9.c'),
        'src/xusbps_intr.c': digest(sdk_root / 'src/xusbps_intr.c'),
        **{path.relative_to(workspace).as_posix(): digest(path) for path in generated},
        'usb_bounded_sdk/manifest.json': digest(workspace / 'usb_bounded_sdk/manifest.json'),
    }
    return generated, external_sources, overlay


def build_app(name, workspace, cpu, gcc, xsa, production_provider=None,
              dev_secure_cleanup=False, dev_usb_bootstrap=False, sd_identity=False):
    secure_cleanup_enabled = (name == 'g6_usb' and
                              (production_provider is not None or dev_secure_cleanup or dev_usb_bootstrap or sd_identity))
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
        if dev_usb_bootstrap:
            defines.append('G6_DEV_USB_BOOTSTRAP')
        if sd_identity:
            defines.append('G6_SD_IDENTITY')
        if secure_cleanup_enabled:
            defines.append('G6_SECURE_CLEANUP')
    sources = [ROOT / 'board/src/ps/src/g3_camera.c']
    include = [cpu / 'include', ROOT / 'board/src/ps/include']
    cleanup_external_sources = {}
    secure_cleanup_usb_sources = []
    secure_cleanup_overlay = None
    if name != 'g3_camera':
        # HSI generates driver sources; official examples stay in the install.
        vendor = gcc.parents[5] / 'data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11/examples'
        sources.append(ROOT / 'board/src/ps/src' / ('g6_usb.c' if name == 'g6_usb' else 'g4_usb.c'))
        if name == 'g6_usb' and secure_cleanup_enabled:
            secure_cleanup_usb_sources, cleanup_external_sources, secure_cleanup_overlay = \
                prepare_secure_cleanup_usb(workspace, gcc)
            sources += [secure_cleanup_usb_sources[-1], *secure_cleanup_usb_sources[:3]]
            include += [secure_cleanup_overlay, ROOT / "board/prj", vendor]
        else:
            sources += [ROOT / 'board/prj/usb_probe.c', vendor / 'xusbps_ch9.c']
        include += [vendor]
    if name == 'g6_usb':
        sources += [ROOT / 'board/src/ps/src' / f for f in ('session.c', 'protocol.c', 'ephemeral.c', 'm09_mlkem.c')]
        sources += [ROOT / 'board/src/third_party/tinycrypt/lib/source' / f for f in ('sha256.c', 'utils.c')]
        if production_provider is not None:
            sources.append(ROOT / 'board/src/ps/src/g6_hmac_drbg.c')
            sources.append(production_provider)
        if sd_identity:
            sources += [ROOT / 'board/src/ps/src' / f for f in
                        ('g6_hmac_drbg.c', 'g6_sd_state.c', 'g6_sd_identity.c')]
        include.append(ROOT / 'board/src/third_party/tinycrypt/lib/include')
        include += [ROOT / 'board/src/third_party', ROOT / 'board/src/third_party/mlkem']
    linker = ROOT / 'board/prj/a9_ddr.ld'
    inputs = [p for p in sources if p.is_relative_to(ROOT)] + [linker, ROOT / 'board/src/ps/include/bsp_compat.h']
    if name != 'g3_camera':
        inputs.append(ROOT / 'board/src/ps/include/usb_recovery.h')
    if name == 'g6_usb':
        inputs += list((ROOT / 'board/src/ps/include').glob('*.h'))
        inputs += list((ROOT / 'board/src/third_party/tinycrypt/lib/include').rglob('*.h'))
        inputs += list((ROOT / 'board/src/third_party/mlkem').rglob('*'))
        if secure_cleanup_enabled:
            inputs += [ROOT / 'board/prj/usb_probe_auto_recovery.c',
                       ROOT / 'board/prj/usb_probe.c',
                       ROOT / 'board/prj/prepare_usb_bounded_sdk.py',
                       ROOT / 'board/src/ps/diag/usb_bounded_sdk_policy.h']
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
    if production_provider is not None:
        forbidden = {'eye_mlkem_dec', 'eye_mlkem_check_sk',
                     'g6_production_read_mlkem512_private_key', 'g6_sk_load',
                     'g6_seed_load', 'g6_ready', 'random_seed', 'random_counter'}
        present = sorted(forbidden.intersection(abi))
        if present:
            raise RuntimeError('Production ELF contains forbidden development/private-key symbols: ' +
                               ', '.join(present))
        required = {'eye_hmac_drbg_instantiate', 'eye_hmac_drbg_generate',
                    'eye_hmac_drbg_reseed', 'g6_production_security_init',
                    'g6_production_read_mlkem512_public_key',
                    'g6_production_mlkem512_decapsulate', 'g6_production_entropy_bytes',
                    'g6_production_security_shutdown', 'g6_secure_cleanup_diag',
                    'secure_cleanup', 'secure_tx_quiesce', 'secure_tx_wipe',
                    'secure_tx_rebuild', 'usb_cdc_secure_cleanup_tx'}
        missing = sorted(required.difference(abi))
        if missing:
            raise RuntimeError('Production ELF omits required security symbols: ' +
                               ', '.join(missing))
    if secure_cleanup_enabled:
        required_cleanup = {'g6_secure_cleanup_diag', 'secure_cleanup',
                            'secure_tx_quiesce', 'secure_tx_wipe',
                            'secure_tx_rebuild', 'usb_cdc_secure_cleanup_tx'}
        missing_cleanup = sorted(required_cleanup.difference(abi))
        if missing_cleanup:
            raise RuntimeError('G6 cleanup ELF omits required symbols: ' +
                               ', '.join(missing_cleanup))
    expected = {'g3_job': 128, 'g3_frame': 65600, 'g3_sealed': 68096}
    if name == 'g6_usb':
        if production_provider is None and not dev_usb_bootstrap and not sd_identity:
            expected.update(g6_sk_load=1632, g6_seed_load=32, g6_ready=4)
        expected.update(g6_status=4)
        expected.update(g6_frames=4, g6_dropped=4, g6_control_errors=4,
                        g6_capture_errors=4, g6_transport_errors=4,
                        g6_fatal_errors=4, g6_disconnects=4,
                        g6_fault_inject=4, g6_injected_capture_errors=4)
        if secure_cleanup_enabled:
            expected['g6_secure_cleanup_diag'] = 120
    owned = {}
    for key, size in expected.items():
        address, actual = abi.get(key, (0, 0))
        if actual != size or address % 64 or not 0x100000 <= address <= 0x40000000 - size:
            raise RuntimeError(f'Invalid ELF-owned DDR ABI: {name}/{key}')
        owned[key] = dict(address=address, size=size)
    if name == 'g6_usb' and production_provider is not None:
        # Include statically allocated production state needed by the AP0
        # cleanup readback. Only TX needs cache-line alignment; the other
        # CPU-owned byte buffers require word-aligned AP0 reads.
        software_owned = {
            'tx': (1472, 64),
            'hello': (48, 4),
            'ack': (48, 4),
            'session': (192, 4),
            'production_drbg': (72, 4),
        }
        for key, (size, alignment) in software_owned.items():
            address, actual = abi.get(key, (0, 0))
            if (actual != size or address % alignment or
                    not 0x100000 <= address <= 0x40000000 - size):
                raise RuntimeError(f'Invalid production-owned DDR ABI: {key}')
            owned[key] = dict(address=address, size=size)
        ranges = sorted((entry['address'], entry['address'] + entry['size'], key)
                        for key, entry in owned.items())
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1]:
                raise RuntimeError('Overlapping production-owned DDR ranges: ' +
                                   previous[2] + ' / ' + current[2])
    if name == 'g6_usb' and dev_usb_bootstrap:
        forbidden_bootstrap = {'g6_sk_load', 'g6_seed_load', 'g6_ready',
                               'g6_production_security_init', 'production_drbg'}
        if forbidden_bootstrap.intersection(abi) or 'usb_bootstrap' not in abi:
            raise RuntimeError('Development USB bootstrap ELF profile isolation failed')
    if name == 'g6_usb' and sd_identity:
        forbidden_sd = {'g6_sk_load', 'g6_seed_load', 'g6_ready', 'usb_bootstrap',
                        'random_seed', 'random_counter', 'g6_production_security_init'}
        required_sd = {'g6_sd_identity_init', 'g6_sd_identity_random',
                       'g6_sd_identity_shutdown', 'eye_sd_state_random', 'f_sync'}
        if forbidden_sd.intersection(abi) or required_sd.difference(abi):
            raise RuntimeError('SD identity ELF profile isolation failed')
    if name == 'g6_usb' and (dev_secure_cleanup or dev_usb_bootstrap):
        # Bind every development secret/readback range to this ELF so a later
        # read-only AP0 capture can verify terminal-fault cleanup by identity.
        development_owned = {
            'private_key': (1632, 4),
            'random_seed': (32, 4),
            'random_counter': (8, 4),
            'tx': (1472, 64),
            'session': (192, 4),
            'hello': (48, 4),
            'ack': (48, 4),
        }
        for key, (size, alignment) in development_owned.items():
            address, actual = abi.get(key, (0, 0))
            if (actual != size or address % alignment or
                    not 0x100000 <= address <= 0x40000000 - size):
                raise RuntimeError(f'Invalid development-owned DDR ABI: {key}')
            owned[key] = dict(address=address, size=size)
        ranges = sorted((entry['address'], entry['address'] + entry['size'], key)
                        for key, entry in owned.items())
        for previous, current in zip(ranges, ranges[1:]):
            if current[0] < previous[1]:
                raise RuntimeError('Overlapping development-owned DDR ranges: ' +
                                   previous[2] + ' / ' + current[2])
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
    if secure_cleanup_usb_sources:
        map_text = (build / 'g6_usb.map').read_text(encoding='utf-8', errors='replace')
        for source in secure_cleanup_usb_sources[:3]:
            object_path = build / f'{sources.index(source)}_{source.stem}.o'
            if str(object_path) not in map_text:
                raise RuntimeError('Link map omits bounded USB cleanup source: ' + str(source))
        if ('libxil.a(usbps_v2_11_xusbps_endpoint.o)' in map_text or
                'libxil.a(usbps_v2_11_xusbps_intr.o)' in map_text):
            raise RuntimeError('Unpatched USBPS endpoint/interrupt object linked into G6 cleanup profile')
    manifest = dict(xsa=str(xsa), xsa_sha256=digest(xsa), application=name,
                    bsp_sha256=digest(cpu / 'lib/libxil.a'),
                    sources=hashes,
                    owned=owned, board_validated=False,
                    artifacts={p.relative_to(workspace).as_posix(): digest(p) for p in
                               (elf, build / (name + '.map'), app / '_ide/bitstream/m01.bit', app / '_ide/psinit/ps7_init.tcl')})
    if cleanup_external_sources:
        manifest['external_sources'] = cleanup_external_sources
        manifest['external_sources_root'] = 'tool-root'
        manifest['secure_cleanup_implementation'] = 'bounded_usbps_overlay_and_dma_gcm_frame_tx_callbacks'
    if name == 'g6_usb':
        manifest['protocol_suites'] = [2] if production_provider is not None or sd_identity else [1, 2]
        manifest['ephemeral_key_storage'] = 'application_ram_only'
        manifest['ephemeral_keygen_source'] = ('provider_entropy_64_bytes' if production_provider is not None
                                              else 'sd_persistent_secret_ratchet_no_fresh_entropy' if sd_identity
                                              else 'pc_known_development_seed_no_forward_secrecy_claim')
        if production_provider is not None:
            manifest['security_profile'] = 'external_provider_unvalidated'
            manifest['production_secure_cleanup'] = manifest['secure_cleanup_implementation']
        elif sd_identity:
            manifest['security_profile'] = 'experimental_sd_local_identity'
            manifest['development_secure_cleanup'] = manifest['secure_cleanup_implementation']
            manifest['sd_identity'] = dict(files=['EYEKEY.BIN', 'EYERNG0.BIN', 'EYERNG1.BIN'],
                                           random_state_bytes=80, identity_or_seed_embedded=False,
                                           host_secret_provisioning=False,
                                           physical_durability_validated=False,
                                           fatfs_ctrl_sync='amd_noop_host_idle_dat0_poll_and_readback',
                                           rollback_protected=False, fresh_entropy=False)
        elif dev_usb_bootstrap:
            manifest['security_profile'] = 'development_usb_bootstrap_secure_cleanup'
            manifest['development_secure_cleanup'] = manifest['secure_cleanup_implementation']
            manifest['usb_bootstrap'] = dict(version=1, total_bytes=1696,
                                             trusted_local_usb_only=True,
                                             identity_and_seed_storage='volatile_ram',
                                             identity_or_seed_embedded=False)
        elif dev_secure_cleanup:
            manifest['security_profile'] = 'development_jtag_mailbox_secure_cleanup'
            manifest['development_secure_cleanup'] = manifest['secure_cleanup_implementation']
        else:
            manifest['security_profile'] = 'development_jtag_mailbox'
        manifest['development_provisioning_required'] = production_provider is None and not sd_identity
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
    parser.add_argument('--g6-dev-secure-cleanup', action='store_true',
                        help='Add bounded USB/DMA cleanup to the development JTAG/host-seed profile; remains experimental')
    parser.add_argument('--g6-dev-usb-bootstrap', action='store_true',
                        help='Explicit development-only USB identity/fresh PC seed bootstrap, no JTAG mailbox or SD secrets')
    parser.add_argument('--g6-sd-identity', action='store_true',
                        help='Experimental SD private identity and persistent random state; no PC secret bootstrap')
    args = parser.parse_args()
    xsa, workspace, tools = args.xsa.resolve(), args.output.resolve(), args.tool_root.resolve()
    provider_source = args.g6_production_provider.resolve() if args.g6_production_provider else None
    if args.g6_sd_identity and ('g6_usb' not in args.apps or args.g6_dev_usb_bootstrap or
                                args.g6_dev_secure_cleanup or provider_source is not None):
        parser.error('--g6-sd-identity requires g6_usb and excludes USB/JTAG/production profiles')
    if args.g6_dev_secure_cleanup and 'g6_usb' not in args.apps:
        parser.error('--g6-dev-secure-cleanup requires --apps to include g6_usb')
    if args.g6_dev_secure_cleanup and provider_source is not None:
        parser.error('--g6-dev-secure-cleanup cannot be combined with --g6-production-provider')
    if args.g6_dev_usb_bootstrap and ('g6_usb' not in args.apps or
                                     args.g6_dev_secure_cleanup or provider_source is not None):
        parser.error('--g6-dev-usb-bootstrap requires g6_usb and cannot mix JTAG/production profiles')
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
        if (args.g6_dev_usb_bootstrap and args.boot_images) or args.g6_sd_identity:
            hwh = ET.fromstring(archive.read('system.hwh'))
            parameters = {p.attrib['NAME']: p.attrib.get('VALUE') for p in
                          hwh.findall('.//MODULE[@MODTYPE="processing_system7"]/PARAMETERS/PARAMETER')}
            if (parameters.get('PCW_SD0_PERIPHERAL_ENABLE') != '1' or
                    parameters.get('PCW_SD0_SD0_IO') != 'MIO 40 .. 45'):
                parser.error('SD bootstrap requires this XSA to enable SD0 on board MIO40..45')
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
    cpu, gcc = build_bsp(workspace, xsa, tools, args.boot_images, args.g6_sd_identity)
    manifests = {}
    for name in args.apps:
        manifests[name] = build_app(name, workspace, cpu, gcc, xsa,
                                    provider_for_build if name == 'g6_usb' else None,
                                    args.g6_dev_secure_cleanup and name == 'g6_usb',
                                    args.g6_dev_usb_bootstrap and name == 'g6_usb',
                                    args.g6_sd_identity and name == 'g6_usb')
        (workspace / (name + '_manifest.json')).write_text(json.dumps(manifests[name], indent=2) + '\n', encoding='utf-8')
        print('ARM_ELF_OK', name, flush=True)
    if args.boot_images:
        fsbl = build_boot_images(workspace, cpu, gcc, tools, manifests, xsa)
        for name, manifest in manifests.items():
            for path in (fsbl, fsbl.with_suffix('.map'), workspace / name / 'boot/BOOT.BIN'):
                manifest['artifacts'][path.relative_to(workspace).as_posix()] = digest(path)
            manifest['development_provisioning_required'] = (
                manifest.get('security_profile', '').startswith('development_'))
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
    external_inputs = {}
    for name, manifest in manifests.items():
        for external_path, external_hash in manifest.get('external_sources', {}).items():
            local = workspace / external_path
            sdk = tools / 'Vitis/data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11' / external_path
            target = local if local.is_file() else sdk
            if not target.is_file() or digest(target) != external_hash:
                raise RuntimeError('External build input missing or changed: ' + external_path)
            external_inputs[str(target.resolve())] = external_hash
    (workspace / 'software_build.json').write_text(json.dumps(dict(
        xsa_sha256=xsa_hash, tool_root=str(tools), applications=list(manifests),
        g6_dev_secure_cleanup=args.g6_dev_secure_cleanup,
        g6_dev_usb_bootstrap=args.g6_dev_usb_bootstrap,
        g6_sd_identity=args.g6_sd_identity,
        generated_inputs=build_inputs, external_inputs=external_inputs,
        build_scripts={p.relative_to(ROOT).as_posix(): digest(p) for p in
                       (ROOT / 'board/prj/build_software.py', ROOT / 'board/prj/generate_bsp.tcl',
                        ROOT / 'board/prj/arm_startup.py')},
        build_method='classic_hsi_arm_gcc', boot_images=args.boot_images,
        board_validated=False), indent=2) + '\n', encoding='utf-8')
    print('SOFTWARE_BUILD_OK', workspace, flush=True)


if __name__ == '__main__':
    main()
