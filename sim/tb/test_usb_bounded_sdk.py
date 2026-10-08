from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
DRIVER_ROOT = Path(os.environ.get("EYEPQC_TOOL_ROOT", "E:/fpg/2026.1")) / (
    "Vitis/data/embeddedsw/XilinxProcessorIPLib/drivers/usbps_v2_11"
)
GENERATOR = ROOT / "prj" / "prepare_usb_bounded_sdk.py"
MOCK_C = ROOT / "sim" / "tb" / "test_usb_bounded_sdk_mock.c"


def generate(tmp: Path) -> tuple[Path, dict]:
    subprocess.run(
        [
            sys.executable, str(GENERATOR), "--source-root", str(DRIVER_ROOT),
            "--out", str(tmp),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    overlay = tmp / "usb_bounded_sdk" / "src"
    manifest = json.loads((tmp / "usb_bounded_sdk" / "manifest.json").read_text())
    return overlay, manifest


def test_hash_pinned_patch_and_ch9_failure_routing():
    with tempfile.TemporaryDirectory(prefix="usb-bounded-sdk-") as td:
        overlay, manifest = generate(Path(td))
        assert manifest["inputs"]["endpoint"]["sha256"] == (
            "9331d7b0006f9738459ed0a4417db804ab1062a2b2fb709f98953ee843119575"
        )
        assert manifest["inputs"]["ch9"]["sha256"] == (
            "d30f2ec77c66f8323eea1e0dcb13391b168c7153ed116852665bca17daf68b88"
        )
        for name, expected in manifest["outputs"].items():
            assert hashlib.sha256((overlay / name).read_bytes()).hexdigest() == expected

        endpoint = (overlay / "xusbps_endpoint.c").read_text()
        ch9 = (overlay / "xusbps_ch9.c").read_text()
        assert "XUsbPs_BoundedTripwireSample" in endpoint
        assert "XUsbPs_BoundedQuiesceInEndpoint" in endpoint
        assert endpoint.count("XUsbPs_BoundedQuiesceInEndpoint(") == 2
        assert "for (;;);" not in ch9
        assert ch9.count("++XUsbPs_Ch9DescriptorSendFailures;") == 6
        assert ch9.count("Status = XST_FAILURE;\n\t\t\t\t\t\tError = 1;") == 5
        assert "Status = XUsbPs_StdDevReq(InstancePtr, SetupData);" in ch9
        assert "return XST_FAILURE;" in ch9
        assert "XUsbPs_EpStall(InstancePtr, 0" in ch9


def test_register_mock_compiles_and_runs_when_native_gcc_exists():
    gcc = shutil.which("gcc")
    with tempfile.TemporaryDirectory(prefix="usb-bounded-sdk-mock-") as td:
        temp = Path(td)
        overlay, _ = generate(temp)
        if gcc:
            exe = temp / "usb_bounded_sdk_mock.exe"
            subprocess.run(
                [gcc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                 "-I", str(overlay), str(MOCK_C), "-o", str(exe)],
                check=True,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            assert "PASS" in completed.stdout
        else:
            arm_gcc = Path(
                r"E:\fpg\2026.1\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe"
            )
            assert arm_gcc.is_file(), "No available C compiler for the register-mock harness"
            obj = temp / "usb_bounded_sdk_mock.o"
            subprocess.run(
                [str(arm_gcc), "-std=c99", "-Wall", "-Wextra", "-Werror",
                 "-ffreestanding", "-I", str(overlay), "-c", str(MOCK_C), "-o", str(obj)],
                check=True,
                capture_output=True,
                text=True,
            )
            assert obj.is_file() and obj.stat().st_size > 0


if __name__ == "__main__":
    test_hash_pinned_patch_and_ch9_failure_routing()
    test_register_mock_compiles_and_runs_when_native_gcc_exists()
    print("USB_BOUNDED_SDK_TESTS_PASS 2/2")
