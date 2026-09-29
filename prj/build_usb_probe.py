"""Build a temporary USB CDC throughput probe from the USB0 XSA."""
import os
from pathlib import Path
import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[1]
root = Path(os.environ.get("EYEPQC_TOOL_ROOT", "D:/AmdDesignTools/2026.1"))
xsa = Path(os.environ.get("EYEPQC_USB_PROBE_XSA", repo / "build/vivado/usb_probe_1/m01.xsa"))
workspace = Path(os.environ.get("EYEPQC_USB_PROBE_VITIS", repo / "build/vitis/usb_probe_1"))
vendor = root / "data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11/examples"
if not xsa.is_file() or workspace.exists():
    raise RuntimeError("USB XSA missing or USB probe workspace already exists")
client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(name="usb_platform", hw_design=str(xsa),
        cpu="ps7_cortexa9_0", os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    if platform.build() != BuildResponse.SUCCESS:
        raise RuntimeError("USB platform failed")
    app = client.create_app_component(name="usb_probe",
        platform=client.find_platform_in_repos("usb_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "prj"), files=["usb_probe.c"], dest_dir_in_cmp="src")
    app.import_files(from_loc=str(vendor), files=["xusbps_ch9.c", "xusbps_ch9.h"],
                     dest_dir_in_cmp="src")
    app.set_app_config(key="USER_COMPILE_OPTIMIZATION_LEVEL", values="-O3")
    if app.build() != BuildResponse.SUCCESS:
        raise RuntimeError("USB application failed")
    print("USB_PROBE_ELF_OK", workspace / "usb_probe/build/usb_probe.elf")
finally:
    vitis.dispose()
