"""Build G4/G5/G6 camera-to-USB Standalone app from a USB-enabled G3 XSA."""
import os
from pathlib import Path
import shutil
import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[1]
root = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
xsa = Path(os.environ["EYEPQC_G4_XSA"])
workspace = Path(os.environ["EYEPQC_G4_VITIS"])
app_name = os.environ.get("EYEPQC_USB_APP", "g4_usb")
if app_name not in ("g4_usb", "g5_usb", "g6_usb"):
    raise RuntimeError("EYEPQC_USB_APP must be g4_usb, g5_usb or g6_usb")
vendor = root / "data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11/examples"
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("Use a fresh workspace and completed G4 XSA")
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="g4_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS:
        raise RuntimeError("G4 platform failed")
    app = client.create_app_component(name=app_name,
        platform=client.find_platform_in_repos("g4_platform"),
        domain="standalone_a9_0", template="empty_application")
    sources = ["g3_camera.c", "g6_usb.c" if app_name == "g6_usb" else "g4_usb.c"]
    if app_name == "g6_usb":
        sources += ["session.c", "protocol.c", "m09_mlkem.c"]
    app.import_files(from_loc=str(repo / "src/ps/src"), files=sources, dest_dir_in_cmp="src")
    app.import_files(from_loc=str(repo / "src/ps/include"), files=["bsp_compat.h"], dest_dir_in_cmp="src")
    app.import_files(from_loc=str(repo / "prj"), files=["usb_probe.c"], dest_dir_in_cmp="src")
    app.import_files(from_loc=str(vendor), files=["xusbps_ch9.c", "xusbps_ch9.h"],
                     dest_dir_in_cmp="src")
    definitions = ["G4_USB", "USB_LIBRARY"]
    if app_name == "g5_usb":
        definitions.append("G5_USB")
    if app_name == "g6_usb":
        definitions.append("G6_USB")
        app.import_files(from_loc=str(repo / "src/third_party/tinycrypt/lib/source"),
                         files=["sha256.c", "utils.c"], dest_dir_in_cmp="src")
        for name in ("session.h", "protocol.h"):
            shutil.copy2(repo / "src/ps/include" / name, workspace / app_name / "src" / name)
        shutil.copytree(repo / "src/third_party/mlkem", workspace / app_name / "src/mlkem")
        shutil.copytree(repo / "src/third_party/tinycrypt", workspace / app_name / "src/tinycrypt")
        app.set_app_config(key="USER_INCLUDE_DIRECTORIES", values=["mlkem", "tinycrypt/lib/include"])
        linker = workspace / app_name / "src/lscript.ld"
        original = linker.read_text()
        old = "_STACK_SIZE = DEFINED(_STACK_SIZE) ? _STACK_SIZE : 0x2000;"
        if old not in original:
            raise RuntimeError("Unexpected linker stack setting")
        linker.write_text(original.replace(old, old.replace("0x2000", "0x8000")))
    app.set_app_config(key="USER_COMPILE_DEFINITIONS", values=definitions)
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    if app.build() != BuildResponse.SUCCESS:
        raise RuntimeError("G4 application failed")
    print("USB_ELF_OK", workspace / app_name / "build" / (app_name + ".elf"))
finally:
    vitis.dispose()
