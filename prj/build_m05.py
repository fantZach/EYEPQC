"""Fresh native Vitis Standalone build, using the XSA's DMA/interrupt configuration."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[1]
xsa = Path(os.environ["EYEPQC_M05_XSA"]).resolve()
workspace = Path(os.environ["EYEPQC_M05_VITIS"]).resolve()
toolroot = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("Use a fresh workspace and a completed M05 XSA")
tracked = [repo / "src/ps/src/camera_dma.c", repo / "src/ps/include/dma_buffers.h",
           *sorted((repo / "src/rtl/camera").glob("*.sv")), repo / "src/rtl/camera/ov5640_jpeg.mem",
           repo / "src/rtl/common/axis_capture_route.sv", repo / "src/rtl/common/axis_byte_packer.sv",
           *[repo / f"prj/{name}" for name in ("build_m01.tcl", "add_m05.tcl", "build_m05.tcl", "build_m05.py")],
           repo / "board/xdc/m05.xdc", repo / "board/xdc/m05_clocks.xdc",
           repo / "board/xdc/m02.xdc", repo / "board/xdc/m01.xdc"]
hashes = {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="dma_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    domain.set_config("os", "standalone_stdin", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS: raise RuntimeError("M05 platform failed")
    app = client.create_app_component(name="camera_dma", platform=client.find_platform_in_repos("dma_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "src/ps/src"), files=["camera_dma.c"], dest_dir_in_cmp="src")
    app.import_files(from_loc=str(repo / "src/ps/include"), files=["dma_buffers.h"], dest_dir_in_cmp="src")
    app.set_app_config(key="USER_COMPILE_WARNINGS_AS_ERRORS", values="-Werror")
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    if app.build() != BuildResponse.SUCCESS: raise RuntimeError("M05 application failed")
    commands = json.loads((workspace / "camera_dma/src/compile_commands.json").read_text())
    own = [c for c in commands if Path(c["file"]).name == "camera_dma.c"]
    if len(own) != 1 or not {"-O3", "-Werror"} <= set(own[0]["command"].split()):
        raise RuntimeError("Expected actual -O3 -Werror compilation")
    for path, digest in hashes.items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Source changed during build: " + path)
    elf = workspace / "camera_dma/build/camera_dma.elf"
    nm = toolroot / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe"
    symbols = subprocess.check_output([str(nm), "-S", str(elf)], text=True).splitlines()
    owned = {}
    for name, size in {"dma_job": 128, "dma_frames": 2 * (65536 + 64), "dma_packet": 65536 + 64}.items():
        entry = [s.split() for s in symbols if s.split()[-1:] == [name]]
        if len(entry) != 1 or int(entry[0][1], 16) != size: raise RuntimeError("Unexpected ABI: " + name)
        address = int(entry[0][0], 16)
        if address % 64 or address < 0x100000 or address + size > 0x40000000:
            raise RuntimeError("Unexpected owned DDR address")
        owned[name] = dict(address=address, size=size)
    artifacts = [elf, workspace / "camera_dma/_ide/bitstream/m01.bit",
                 workspace / "camera_dma/_ide/psinit/ps7_init.tcl"]
    manifest = dict(xsa=str(xsa), xsa_sha256=hashlib.sha256(xsa.read_bytes()).hexdigest(),
        sources=hashes, owned=owned, artifacts={p.relative_to(workspace).as_posix():
            hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}, board_validated=False)
    (workspace / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("M05_ELF_OK", elf)
finally:
    vitis.dispose()
