"""Run with Vitis 2026.1: vitis -s board/prj/build_m01.py (not system Python).

EYEPQC_M01_XSA / EYEPQC_M01_VITIS optionally select input / fresh output.
"""
import os
import hashlib
import json
from pathlib import Path

import vitis
from build_pb2 import BuildResponse

repo = Path(__file__).resolve().parents[2]
xsa = Path(os.environ.get("EYEPQC_M01_XSA", repo / "build/vivado/m01/m01.xsa")).resolve()
workspace = Path(os.environ.get("EYEPQC_M01_VITIS", repo / "build/vitis/m01")).resolve()
if not xsa.is_file():
    raise FileNotFoundError(f"Build hardware first: {xsa}")
if workspace.exists():
    raise FileExistsError(f"Use a fresh output directory: {workspace}")

client = vitis.create_client()
try:
    client.set_workspace(str(workspace))
    platform = client.create_platform_component(
        name="m01_platform", hw_design=str(xsa), cpu="ps7_cortexa9_0",
        os="standalone", domain_name="standalone_a9_0")
    domain = platform.get_domain("standalone_a9_0")
    domain.set_config("os", "standalone_stdout", "ps7_uart_0")
    domain.set_config("os", "standalone_stdin", "ps7_uart_0")
    domain.set_lib("lwip220")
    for key, value in {"lwip220_api_mode": "RAW_API", "lwip220_dhcp": "false",
                       "lwip220_ipv6_enable": "false", "lwip220_no_sys_no_timers": "true",
                       "lwip220_tcp_wnd": "8192", "lwip220_tcp_snd_buf": "16384"}.items():
        domain.set_config("lib", key, value, lib_name="lwip220")
    if platform.build() != BuildResponse.SUCCESS:
        raise RuntimeError("Platform build failed")
    # Patch the shared dispatch: initial setup and link recovery both use it.
    phy_files = list(workspace.glob("m01_platform/ps7_cortexa9_0/standalone_a9_0/"
                                   "bsp/libsrc/lwip220/**/xemacpsif_physpeed.c"))
    if len(phy_files) != 1:
        raise RuntimeError("Expected one generated GEM PHY driver")
    phy_file = phy_files[0]
    phy_source = phy_file.read_text()
    dispatch = "static u32_t get_IEEE_phy_speed(XEmacPs *xemacpsp, u32_t phy_addr)\n{"
    identify = ("\tXEmacPs_PhyRead(xemacpsp, phy_addr, PHY_IDENTIFIER_1_REG,\n"
                "\t\t\t\t\t&phy_identity);\n\tif (phy_identity == PHY_TI_IDENTIFIER) {")
    if phy_source.count(dispatch) != 1 or phy_source.count(identify) != 1:
        raise RuntimeError("AMD PHY dispatch changed; inspect before patching")
    phy_adapter = (repo / "board/src/ps/src/m01_yt8521.inc").read_bytes()
    patched = phy_source.replace(dispatch, phy_adapter.decode() + "\n" + dispatch)
    patched = patched.replace(identify,
        "\tu16_t phy_id2;\n"
        "\tif (XEmacPs_PhyRead(xemacpsp, phy_addr, 2, &phy_identity) != XST_SUCCESS ||\n"
        "\t    XEmacPs_PhyRead(xemacpsp, phy_addr, 3, &phy_id2) != XST_SUCCESS)\n"
        "\t\treturn XST_FAILURE;\n"
        '\txil_printf("M01 PHY ID=%04x:%04x addr=%u\\r\\n", phy_identity, phy_id2, phy_addr);\n'
        "\tif (phy_identity == 0 && phy_id2 == 0x011a)\n"
        "\t\treturn m01_yt8521_speed(xemacpsp, phy_addr);\n"
        "\tif (phy_identity != PHY_MARVELL_IDENTIFIER && phy_identity != PHY_TI_IDENTIFIER &&\n"
        "\t    phy_identity != PHY_REALTEK_IDENTIFIER && phy_identity != PHY_XILINX_PCS_PMA_ID1 &&\n"
        "\t    phy_identity != PHY_ADI_IDENTIFIER) return XST_FAILURE;\n"
        "\tif (phy_identity == PHY_TI_IDENTIFIER) {")
    phy_file.write_text(patched)
    # The other native caller must not turn a failed recovery into link-up.
    adapter_file = phy_file.with_name("xadapter.c")
    adapter_source = adapter_file.read_text()
    recover = "\t\t\t\tXEmacPs_SetOperatingSpeed(xemacp, link_speed);"
    if adapter_source.count(recover) != 1:
        raise RuntimeError("AMD link recovery changed; inspect before patching")
    recovered = adapter_source.replace(recover,
        "\t\t\t\tif (link_speed == XST_FAILURE) return;\n" + recover)
    adapter_file.write_text(recovered)
    if platform.build() != BuildResponse.SUCCESS or phy_file.read_text() != patched:
        raise RuntimeError("Patched platform build failed or regenerated PHY driver")
    if adapter_file.read_text() != recovered:
        raise RuntimeError("Platform regenerated the link recovery guard")
    app = client.create_app_component(
        name="m01", platform=client.find_platform_in_repos("m01_platform"),
        domain="standalone_a9_0", template="empty_application")
    app.import_files(from_loc=str(repo / "board/src/ps/src"), files=["m01.c"],
                     dest_dir_in_cmp="src")
    app.set_app_config(key="USER_COMPILE_WARNINGS_AS_ERRORS", values="-Werror")
    if app.build() != BuildResponse.SUCCESS:
        raise RuntimeError("Application build failed")
    elf_files = list(workspace.glob("m01/build/m01.elf"))
    if not elf_files:
        raise RuntimeError("No ELF generated; inspect build errors")
    source = (workspace / "m01/src/m01.c").read_bytes()
    if source != (repo / "board/src/ps/src/m01.c").read_bytes():
        raise RuntimeError("Source changed during build; rebuild before delivery")
    if phy_adapter != (repo / "board/src/ps/src/m01_yt8521.inc").read_bytes():
        raise RuntimeError("PHY adapter changed during build; rebuild before delivery")
    manifest = {"xsa": str(xsa), "xsa_sha256": hashlib.sha256(xsa.read_bytes()).hexdigest(),
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "phy_adapter_sha256": hashlib.sha256(phy_adapter).hexdigest(),
                "phy_driver_sha256": hashlib.sha256(phy_file.read_bytes()).hexdigest(),
                "link_driver_sha256": hashlib.sha256(adapter_file.read_bytes()).hexdigest(),
                "elf_sha256": hashlib.sha256(elf_files[0].read_bytes()).hexdigest(),
                "board_validated": False}
    (workspace / "build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("M01_ELF_OK", elf_files)
finally:
    vitis.dispose()
