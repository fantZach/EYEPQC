"""Build the G3 camera/AES-GCM Standalone A9 application from a fresh XSA."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[1]
xsa = Path(os.environ["EYEPQC_G3_XSA"]).resolve()
workspace = Path(os.environ["EYEPQC_G3_VITIS"]).resolve()
toolroot = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("Use a fresh workspace and a completed G3 XSA")
tracked = [repo / "src/ps/src/g3_camera.c",
           *sorted((repo / "src/rtl/camera").glob("*.sv")),
           repo / "src/rtl/camera/ov5640_jpeg.mem",
           repo / "src/rtl/common/axis_capture_route.sv",
           repo / "src/rtl/common/axis_byte_packer.sv",
           *sorted((repo / "src/rtl/crypto/secworks_aes").glob("*.v")),
           *[repo / f"src/rtl/crypto/{name}.sv" for name in
             ("gf128_mul", "ghash", "aes_gcm_encrypt", "aes_gcm_regs", "aes_gcm_axis")],
           *[repo / f"prj/{name}" for name in
             ("build_m01.tcl", "add_m05.tcl", "build_m05.tcl", "build_g3.tcl", "build_g3.py")],
           *[repo / f"board/xdc/{name}.xdc" for name in
             ("m01", "m02", "m05", "m05_clocks")]]
hashes = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="g3_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    domain.set_config("os", "standalone_stdin", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS: raise RuntimeError("G3 platform failed")
    app = client.create_app_component(name="g3_camera", platform=client.find_platform_in_repos("g3_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "src/ps/src"), files=["g3_camera.c"], dest_dir_in_cmp="src")
    app.set_app_config(key="USER_COMPILE_WARNINGS_AS_ERRORS", values="-Werror")
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    if app.build() != BuildResponse.SUCCESS: raise RuntimeError("G3 application failed")
    commands = json.loads((workspace / "g3_camera/src/compile_commands.json").read_text())
    own = [c for c in commands if Path(c["file"]).name == "g3_camera.c"]
    if len(own) != 1 or not {"-O3", "-Werror"} <= set(own[0]["command"].split()):
        raise RuntimeError("Expected actual -O3 -Werror compilation")
    for path, digest in hashes.items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Source changed during build: " + path)
    elf = workspace / "g3_camera/build/g3_camera.elf"
    nm = toolroot / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe"
    symbols = subprocess.check_output([str(nm), "-S", str(elf)], text=True).splitlines()
    owned = {}
    for name, size in {"g3_job": 128, "g3_frame": 65600, "g3_sealed": 68096}.items():
        entries = [s.split() for s in symbols if s.split()[-1:] == [name]]
        if len(entries) != 1 or int(entries[0][1], 16) != size:
            raise RuntimeError("Unexpected owned ABI: " + name)
        address = int(entries[0][0], 16)
        if address % 64 or address < 0x100000 or address + size > 0x40000000:
            raise RuntimeError("Unexpected owned DDR address: " + name)
        owned[name] = dict(address=address, size=size)
    artifacts = [elf, workspace / "g3_camera/_ide/bitstream/m01.bit",
                 workspace / "g3_camera/_ide/psinit/ps7_init.tcl"]
    manifest = dict(xsa=str(xsa), xsa_sha256=hashlib.sha256(xsa.read_bytes()).hexdigest(),
        sources=hashes, owned=owned, artifacts={p.relative_to(workspace).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}, board_validated=False)
    (workspace / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("G3_ELF_OK", elf)
finally:
    vitis.dispose()
