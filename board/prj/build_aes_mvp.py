"""Vitis 2026.1 native API; fresh Standalone platform, no lwIP dependency."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[2]
xsa = Path(os.environ["EYEPQC_MVP_XSA"]).resolve()
workspace = Path(os.environ["EYEPQC_MVP_VITIS"]).resolve()
toolroot = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("Build hardware first and use a fresh Vitis workspace")
sources = [repo / "board/src/ps/src/aes_image_mvp.c", repo / "board/src/ps/src/mvp_gcm.c",
           repo / "board/src/ps/include/mvp_gcm.h"]
rtl = [repo / "board/src/rtl/crypto/aes_axi_lite.sv",
       *sorted((repo / "board/src/rtl/crypto/secworks_aes").glob("*.v"))]
tracked = [*sources, *rtl, Path(__file__).resolve(),
           repo / "board/prj/build_aes_mvp.tcl", repo / "board/prj/build_m01.tcl"]
hashes = {str(p.relative_to(repo)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
          for p in tracked}
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="mvp_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    domain.set_config("os", "standalone_stdin", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS: raise RuntimeError("MVP platform failed")
    app = client.create_app_component(name="aes_mvp", platform=client.find_platform_in_repos("mvp_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "board/src/ps/src"), files=["aes_image_mvp.c", "mvp_gcm.c"], dest_dir_in_cmp="src")
    app.import_files(from_loc=str(repo / "board/src/ps/include"), files=["mvp_gcm.h"], dest_dir_in_cmp="src")
    app.set_app_config(key="USER_COMPILE_WARNINGS_AS_ERRORS", values="-Werror")
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    if app.build() != BuildResponse.SUCCESS: raise RuntimeError("MVP application failed")
    commands = json.loads((workspace / "aes_mvp/src/compile_commands.json").read_text())
    for source in sources[:2]:
        own = [item for item in commands if Path(item["file"]).name == source.name]
        if len(own) != 1 or "-O3" not in own[0]["command"].split():
            raise RuntimeError("Expected actual -O3 compilation: " + source.name)
    for path, digest in hashes.items():
        if hashlib.sha256((repo / path).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Source changed during build: " + path)
    elf = workspace / "aes_mvp/build/aes_mvp.elf"
    nm = toolroot / "gnu/aarch32/nt/gcc-arm-none-eabi/bin/arm-none-eabi-nm.exe"
    symbols = subprocess.check_output([str(nm), "-S", str(elf)], text=True).splitlines()
    job = [line.split() for line in symbols if line.split()[-1:] == ["mvp_job"]]
    job_size = 524288 + 76
    if len(job) != 1 or int(job[0][1], 16) != job_size: raise RuntimeError("Unexpected mailbox ABI")
    artifacts = [elf, workspace / "aes_mvp/_ide/bitstream/m01.bit",
                 workspace / "aes_mvp/_ide/psinit/ps7_init.tcl"]
    manifest = dict(optimization="-O3", xsa=str(xsa), xsa_sha256=hashlib.sha256(xsa.read_bytes()).hexdigest(),
        sources=hashes, artifacts={str(p.relative_to(workspace)).replace("\\", "/"):
            hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts},
        mailbox_address=int(job[0][0], 16), mailbox_size=job_size, board_validated=False)
    (workspace / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("AES_MVP_ELF_OK", elf)
finally:
    vitis.dispose()
