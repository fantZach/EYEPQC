"""Build M09 Cortex-A9 Standalone ELF from an existing board-validated XSA."""
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

xsa = Path(os.environ.get("EYEPQC_M09_XSA", repo / "build/vivado/m01_hynix_v2/m01.xsa")).resolve()
workspace = Path(os.environ.get("EYEPQC_M09_VITIS", repo / "build/vitis/m09_board_1")).resolve()
toolroot = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("Provide an existing board XSA and a fresh EYEPQC_M09_VITIS directory")
sources = [repo / "board/src/ps/src/m09.c", repo / "board/src/ps/src/m09_mlkem.c",
           *sorted((repo / "board/src/third_party/mlkem").rglob("*.*"))]
hashes = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in sources if p.is_file()}
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="m09_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    domain.set_config("os", "standalone_stdin", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS: raise RuntimeError("M09 platform failed")
    app = client.create_app_component(name="m09", platform=client.find_platform_in_repos("m09_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "board/src/ps/src"), files=["m09.c", "m09_mlkem.c"],
                     dest_dir_in_cmp="src")
    shutil.copytree(repo / "board/src/third_party/mlkem", workspace / "m09/src/mlkem")
    app.set_app_config(key="USER_INCLUDE_DIRECTORIES", values=["mlkem"])
    app.set_app_config(key="USER_COMPILE_WARNINGS_AS_ERRORS", values="-Werror")
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    linker = workspace / "m09/src/lscript.ld"
    original = linker.read_text()
    if "_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x2000;" not in original:
        raise RuntimeError("Unexpected linker stack setting")
    linker.write_text(original.replace("_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x2000;",
                                       "_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x8000;"))
    if app.build() != BuildResponse.SUCCESS: raise RuntimeError("M09 application failed")
    for path, digest in hashes.items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Source changed during build: " + path)
    elf = workspace / "m09/build/m09.elf"
    nm = toolroot / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe"
    symbols = subprocess.check_output([str(nm), "-S", str(elf)], text=True).splitlines()
    owned = {}
    for name, size in {"m09_job": 128, "m09_sk": 1632, "m09_ct": 768}.items():
        entries = [s.split() for s in symbols if s.split()[-1:] == [name]]
        if len(entries) != 1 or int(entries[0][1], 16) != size:
            raise RuntimeError("Unexpected owned ABI: " + name)
        address = int(entries[0][0], 16)
        if address % 64 or address < 0x100000 or address + size > 0x40000000:
            raise RuntimeError("Unexpected owned DDR address: " + name)
        owned[name] = dict(address=address, size=size)
    require_disjoint_ranges(((name, item["address"], item["size"])
                             for name, item in owned.items()), "ELF-owned M09 buffers")
    manifest = dict(xsa=str(xsa), xsa_sha256=hashlib.sha256(xsa.read_bytes()).hexdigest(),
                    sources=hashes, owned=owned, elf=str(elf), elf_sha256=hashlib.sha256(elf.read_bytes()).hexdigest(),
                    board_validated=False)
    (workspace / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("M09_ELF_OK", elf)
finally:
    vitis.dispose()
