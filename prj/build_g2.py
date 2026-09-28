"""Build a fresh G2 Standalone A9 application from the routed XSA."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[1]
xsa = Path(os.environ["EYEPQC_G2_XSA"]).resolve()
workspace = Path(os.environ["EYEPQC_G2_VITIS"]).resolve()
toolroot = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("Use a fresh workspace and a completed G2 XSA")
tracked = [repo / "src/ps/src/g2_crypto.c",
           repo / "src/rtl/common/axis_byte_packer.sv",
           *sorted((repo / "src/rtl/crypto/secworks_aes").glob("*.v")),
           *[repo / f"src/rtl/crypto/{name}.sv" for name in
             ("gf128_mul", "ghash", "aes_gcm_encrypt", "aes_gcm_regs", "aes_gcm_axis")],
           *[repo / f"prj/{name}" for name in
             ("build_m01.tcl", "build_g2.tcl", "add_g2.tcl", "build_g2.py")],
           repo / "board/xdc/m01.xdc"]
hashes = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="g2_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    domain.set_config("os", "standalone_stdin", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS: raise RuntimeError("G2 platform failed")
    app = client.create_app_component(name="g2_crypto", platform=client.find_platform_in_repos("g2_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "src/ps/src"), files=["g2_crypto.c"], dest_dir_in_cmp="src")
    app.set_app_config(key="USER_COMPILE_WARNINGS_AS_ERRORS", values="-Werror")
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    if app.build() != BuildResponse.SUCCESS: raise RuntimeError("G2 application failed")
    commands = json.loads((workspace / "g2_crypto/src/compile_commands.json").read_text())
    own = [c for c in commands if Path(c["file"]).name == "g2_crypto.c"]
    if len(own) != 1 or not {"-O3", "-Werror"} <= set(own[0]["command"].split()):
        raise RuntimeError("Expected actual -O3 -Werror compilation")
    for path, digest in hashes.items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Source changed during build: " + path)
    elf = workspace / "g2_crypto/build/g2_crypto.elf"
    nm = toolroot / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe"
    symbols = subprocess.check_output([str(nm), "-S", str(elf)], text=True).splitlines()
    owned = {}
    for name, size in {"g2_job": 192, "g2_tx": 1472, "g2_rx": 1536}.items():
        entries = [s.split() for s in symbols if s.split()[-1:] == [name]]
        if len(entries) != 1 or int(entries[0][1], 16) != size:
            raise RuntimeError("Unexpected owned ABI: " + name)
        address = int(entries[0][0], 16)
        if address % 64 or address < 0x100000 or address + size > 0x40000000:
            raise RuntimeError("Unexpected owned DDR address: " + name)
        owned[name] = dict(address=address, size=size)
    artifacts = [elf, workspace / "g2_crypto/_ide/bitstream/m01.bit",
                 workspace / "g2_crypto/_ide/psinit/ps7_init.tcl"]
    manifest = dict(xsa=str(xsa), xsa_sha256=hashlib.sha256(xsa.read_bytes()).hexdigest(),
        sources=hashes, owned=owned, artifacts={p.relative_to(workspace).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}, board_validated=False)
    (workspace / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("G2_ELF_OK", elf)
finally:
    vitis.dispose()
