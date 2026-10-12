"""Build M10 Standalone A9 ELF against the existing G3 AES-GCM XSA."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo / "pc/src/host"))
from owned_ddr import require_disjoint_ranges

xsa = Path(os.environ.get("EYEPQC_M10_XSA", repo / "build/vivado/g3_fast_2/m01.xsa")).resolve()
workspace = Path(os.environ.get("EYEPQC_M10_VITIS", repo / "build/vitis/m10_board_1")).resolve()
toolroot = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("Provide a G3 XSA and a fresh EYEPQC_M10_VITIS directory")
sources = [*[repo / f"board/src/ps/src/{name}.c" for name in
             ("m10", "m09_mlkem", "session", "protocol")],
           *[repo / f"board/src/ps/include/{name}.h" for name in ("session", "protocol")],
           *[p for folder in ("mlkem", "tinycrypt") for p in
             (repo / "board/src/third_party" / folder).rglob("*") if p.is_file()]]
hashes = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="m10_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    domain.set_config("os", "standalone_stdin", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS: raise RuntimeError("M10 platform failed")
    app = client.create_app_component(name="m10", platform=client.find_platform_in_repos("m10_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "board/src/ps/src"),
                     files=["m10.c", "m09_mlkem.c", "session.c", "protocol.c"],
                     dest_dir_in_cmp="src")
    app.import_files(from_loc=str(repo / "board/src/third_party/tinycrypt/lib/source"),
                     files=["sha256.c", "utils.c"], dest_dir_in_cmp="src")
    for name in ("session.h", "protocol.h"):
        shutil.copy2(repo / "board/src/ps/include" / name, workspace / "m10/src" / name)
    shutil.copytree(repo / "board/src/third_party/mlkem", workspace / "m10/src/mlkem")
    shutil.copytree(repo / "board/src/third_party/tinycrypt", workspace / "m10/src/tinycrypt")
    app.set_app_config(key="USER_INCLUDE_DIRECTORIES", values=["mlkem", "tinycrypt/lib/include"])
    app.set_app_config(key="USER_COMPILE_WARNINGS_AS_ERRORS", values="-Werror")
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    linker = workspace / "m10/src/lscript.ld"
    original = linker.read_text()
    if "_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x2000;" not in original:
        raise RuntimeError("Unexpected linker stack setting")
    linker.write_text(original.replace("_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x2000;",
                                       "_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x8000;"))
    if app.build() != BuildResponse.SUCCESS: raise RuntimeError("M10 application failed")
    for path, digest in hashes.items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Source changed during build: " + path)
    elf = workspace / "m10/build/m10.elf"
    nm = toolroot / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe"
    symbols = subprocess.check_output([str(nm), "-S", str(elf)], text=True).splitlines()
    owned = {}
    for name, size in {"m10_job": 256, "m10_sk": 1632, "m10_wire": 972}.items():
        entries = [s.split() for s in symbols if s.split()[-1:] == [name]]
        if len(entries) != 1 or int(entries[0][1], 16) != size:
            raise RuntimeError("Unexpected owned ABI: " + name)
        address = int(entries[0][0], 16)
        if address % 64 or address < 0x100000 or address + size > 0x40000000:
            raise RuntimeError("Unexpected owned DDR address: " + name)
        owned[name] = dict(address=address, size=size)
    require_disjoint_ranges(((name, item["address"], item["size"])
                             for name, item in owned.items()), "ELF-owned M10 buffers")
    bit = workspace / "m10/_ide/bitstream/m01.bit"
    if not bit.is_file(): raise RuntimeError("G3 XSA bitstream missing")
    manifest = dict(xsa=str(xsa), xsa_sha256=hashlib.sha256(xsa.read_bytes()).hexdigest(),
                    sources=hashes, owned=owned, elf=str(elf),
                    elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
                    bit_sha256=hashlib.sha256(bit.read_bytes()).hexdigest(), board_validated=False)
    (workspace / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("M10_ELF_OK", elf)
finally:
    vitis.dispose()
