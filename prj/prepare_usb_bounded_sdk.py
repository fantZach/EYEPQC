#!/usr/bin/env python3
"""Generate a hash-pinned, isolated USBPS SDK source overlay.

This never writes into Vitis or a generated BSP. The caller supplies the
embeddedsw usbps_v2_11 driver root and an output workspace directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


PINNED = {
    "endpoint": {
        "relative": Path("src/xusbps_endpoint.c"),
        "sha256": "9331d7b0006f9738459ed0a4417db804ab1062a2b2fb709f98953ee843119575",
    },
    "ch9": {
        "relative": Path("examples/xusbps_ch9.c"),
        "sha256": "d30f2ec77c66f8323eea1e0dcb13391b168c7153ed116852665bca17daf68b88",
    },
}
POLICY = Path(__file__).resolve().parents[1] / "src/ps/diag/usb_bounded_sdk_policy.h"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"strict patch anchor {label!r}: expected once, found {count}")
    return source.replace(old, new, 1)


def patch_endpoint(source: str) -> str:
    source = replace_once(
        source,
        '#include "xusbps.h"\n#include "xusbps_endpoint.h"',
        '#include "xusbps.h"\n#include "xusbps_endpoint.h"\n'
        '#include "usb_bounded_sdk_policy.h"',
        "endpoint policy include",
    )
    source = replace_once(
        source,
        '/************************** Variable Definitions ******************************/',
        '/************************** Variable Definitions ******************************/\n'
        '#define XUSBPS_BOUNDED_FAULT_SLOTS 8U\n'
        'static volatile u32 XUsbPs_BoundedFaultBase[XUSBPS_BOUNDED_FAULT_SLOTS];\n'
        'static volatile u32 XUsbPs_BoundedFaultMask[XUSBPS_BOUNDED_FAULT_SLOTS];\n'
        'static volatile u32 XUsbPs_BoundedFaultOverflow;\n\n'
        'void XUsbPs_BoundedMarkEndpointFaulted(XUsbPs *InstancePtr, u8 EpNum)\n'
        '{\n'
        '\tu32 Slot;\n'
        '\tu32 Base = InstancePtr->Config.BaseAddress;\n'
        '\tfor (Slot = 0; Slot < XUSBPS_BOUNDED_FAULT_SLOTS; ++Slot) {\n'
        '\t\tif (XUsbPs_BoundedFaultBase[Slot] == Base ||\n'
        '\t\t    XUsbPs_BoundedFaultBase[Slot] == 0U) {\n'
        '\t\t\tXUsbPs_BoundedFaultBase[Slot] = Base;\n'
        '\t\t\tXUsbPs_BoundedFaultMask[Slot] |= (1U << EpNum);\n'
        '\t\t\treturn;\n'
        '\t\t}\n'
        '\t}\n'
        '\tXUsbPs_BoundedFaultOverflow = 1U;\n'
        '}\n\n'
        'int XUsbPs_BoundedEndpointIsFaulted(XUsbPs *InstancePtr, u8 EpNum)\n'
        '{\n'
        '\tu32 Slot;\n'
        '\tu32 Base = InstancePtr->Config.BaseAddress;\n'
        '\tif (XUsbPs_BoundedFaultOverflow) return 1;\n'
        '\tfor (Slot = 0; Slot < XUSBPS_BOUNDED_FAULT_SLOTS; ++Slot) {\n'
        '\t\tif (XUsbPs_BoundedFaultBase[Slot] == Base)\n'
        '\t\t\treturn (XUsbPs_BoundedFaultMask[Slot] & (1U << EpNum)) != 0U;\n'
        '\t}\n'
        '\treturn 0;\n'
        '}\n\n'
        'void XUsbPs_BoundedClearEndpointFaults(XUsbPs *InstancePtr)\n'
        '{\n'
        '\tu32 Slot;\n'
        '\tu32 Base = InstancePtr->Config.BaseAddress;\n'
        '\tfor (Slot = 0; Slot < XUSBPS_BOUNDED_FAULT_SLOTS; ++Slot) {\n'
        '\t\tif (XUsbPs_BoundedFaultBase[Slot] == Base) {\n'
        '\t\t\tXUsbPs_BoundedFaultMask[Slot] = 0U;\n'
        '\t\t\tXUsbPs_BoundedFaultBase[Slot] = 0U;\n'
        '\t\t}\n'
        '\t}\n'
        '}',
        "sticky per-controller endpoint fault registry",
    )
    source = replace_once(
        source,
        'EpType = InstancePtr->DeviceConfig.EpCfg[EpNum].In.Type;\n\n'
        '\tXil_DCacheFlushRange((unsigned int)BufferPtr, BufferLen);',
        'EpType = InstancePtr->DeviceConfig.EpCfg[EpNum].In.Type;\n\n'
        '\t/* Fail closed before touching the ring if a previous bounded wait\n'
        '\t * disabled this endpoint.  Disabled endpoints cannot acquire new\n'
        '\t * dTD ownership. */\n'
        '\tRegValue = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,\n'
        '\t\t\t\t   XUSBPS_EPCRn_OFFSET(EpNum));\n'
        '\tif (XUsbPs_BoundedEndpointIsFaulted(InstancePtr, EpNum) ||\n'
        '\t    (RegValue & XUSBPS_EPCR_TXE_MASK) == 0U) {\n'
        '\t\treturn XST_FAILURE;\n'
        '\t}\n\n'
        '\tXil_DCacheFlushRange((unsigned int)BufferPtr, BufferLen);',
        "endpoint enabled guard",
    )
    old = (
        '\t\tdo {\n'
        '\t\t\tRegValue = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress, XUSBPS_CMD_OFFSET);\n'
        '\t\t\tXUsbPs_WriteReg(InstancePtr->Config.BaseAddress, XUSBPS_CMD_OFFSET,\n'
        '\t\t\t\t\tRegValue | XUSBPS_CMD_ATDTW_MASK);\n'
        '\t\t\tTemp = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress, XUSBPS_EPRDY_OFFSET)\n'
        '\t\t\t       & BitMask;\n'
        '\t\t} while (!(XUsbPs_ReadReg(InstancePtr->Config.BaseAddress, XUSBPS_CMD_OFFSET) &\n'
        '\t\t\t   XUSBPS_CMD_ATDTW_MASK));\n\n'
        '\t\tRegValue = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress, XUSBPS_CMD_OFFSET);\n'
        '\t\tXUsbPs_WriteReg(InstancePtr->Config.BaseAddress, XUSBPS_CMD_OFFSET,\n'
        '\t\t\t\tRegValue & ~XUSBPS_CMD_ATDTW_MASK);\n\n'
        '\t\tif (Temp) {\n'
        '\t\t\treturn XST_SUCCESS;\n'
        '\t\t}\n'
    )
    new = (
        '\t\tif (XUsbPs_BoundedTripwireSample(InstancePtr, BitMask, &Temp) !=\n'
        '\t\t    XST_SUCCESS) {\n'
        '\t\t\t/* Request construction above already activated and linked dTDs.\n'
        '\t\t\t * Flush and disable; preserve every descriptor and buffer pointer\n'
        '\t\t\t * if quiescence cannot be proven.  This endpoint stays disabled. */\n'
        '\t\t\tXUsbPs_BoundedMarkEndpointFaulted(InstancePtr, EpNum);\n'
        '\t\t\t(void)XUsbPs_BoundedQuiesceInEndpoint(InstancePtr, EpNum, BitMask,\n'
        '\t\t\t\t\t\t\t  (1U << (EpNum + XUSBPS_EPFLUSH_TX_SHIFT)));\n'
        '\t\t\treturn XST_FAILURE;\n'
        '\t\t}\n'
        '\t\tif (Temp) {\n'
        '\t\t\treturn XST_SUCCESS;\n'
        '\t\t}\n'
    )
    source = replace_once(source, old, new, "ATDTW unbounded loop")
    source = replace_once(
        source,
        '\tStatus = XUsbPs_EpPrime(InstancePtr, EpNum, XUSBPS_EP_DIRECTION_IN);\n\n'
        '\treturn Status;',
        '\tStatus = XUsbPs_EpPrime(InstancePtr, EpNum, XUSBPS_EP_DIRECTION_IN);\n'
        '\tif (Status != XST_SUCCESS) {\n'
        '\t\t/* EpPrime failure leaves this request linked in the ring. */\n'
        '\t\tXUsbPs_BoundedMarkEndpointFaulted(InstancePtr, EpNum);\n'
        '\t\t(void)XUsbPs_BoundedQuiesceInEndpoint(InstancePtr, EpNum, BitMask,\n'
        '\t\t\t\t\t\t\t  (1U << (EpNum + XUSBPS_EPFLUSH_TX_SHIFT)));\n'
        '\t\treturn XST_FAILURE;\n'
        '\t}\n\n'
        '\treturn XST_SUCCESS;',
        "EpPrime fail-closed path",
    )
    return source


def patch_ch9(source: str) -> tuple[str, int]:
    source = replace_once(
        source,
        '#include "xusbps_ch9.h"\n#include "xil_printf.h"',
        '#include "xusbps_ch9.h"\n#include "usb_bounded_sdk_policy.h"\n'
        '#include "xil_printf.h"',
        "CH9 policy include",
    )
    source = replace_once(
        source,
        'static void XUsbPs_StdDevReq(XUsbPs *InstancePtr,\n'
        '\t\t\t     XUsbPs_SetupData *SetupData);',
        'static int XUsbPs_StdDevReq(XUsbPs *InstancePtr,\n'
        '\t\t\t    XUsbPs_SetupData *SetupData);',
        "CH9 declaration status propagation",
    )
    source = replace_once(
        source,
        '/************************** Variable Definitions *****************************/',
        '/************************** Variable Definitions *****************************/\n'
        '/* Readable from a debugger/diagnostic snapshot; incremented on descriptor\n'
        ' * queue failure before the standard-request path stalls EP0. */\n'
        'volatile u32 XUsbPs_Ch9DescriptorSendFailures = 0U;',
        "CH9 telemetry symbol",
    )
    source = replace_once(
        source,
        '\t\t\tXUsbPs_StdDevReq(InstancePtr, SetupData);\n'
        '\t\t\tbreak;',
        '\t\t\tStatus = XUsbPs_StdDevReq(InstancePtr, SetupData);\n'
        '\t\t\tbreak;',
        "CH9 dispatcher status propagation",
    )
    source = replace_once(
        source,
        'static void XUsbPs_StdDevReq(XUsbPs *InstancePtr,\n'
        '\t\t\t     XUsbPs_SetupData *SetupData)\n',
        'static int XUsbPs_StdDevReq(XUsbPs *InstancePtr,\n'
        '\t\t\t    XUsbPs_SetupData *SetupData)\n',
        "CH9 implementation return type",
    )
    source = replace_once(
        source,
        '\tTempPtr = (u8 *)&TmpBuffer;\n\n'
        '\t/* Check that the requested reply length is not bigger than our',
        '\tTempPtr = (u8 *)&TmpBuffer;\n\n'
        '\t/* EP0 can retain DMA ownership after a failed queue/flush. Do not\n'
        '\t * rewrite its static descriptor buffers until controller reset and\n'
        '\t * an explicit clear after verified DMA quiescence. */\n'
        '\tif (XUsbPs_BoundedEndpointIsFaulted(InstancePtr, 0U)) {\n'
        '\t\t++XUsbPs_Ch9DescriptorSendFailures;\n'
        '\t\tXUsbPs_EpStall(InstancePtr, 0, XUSBPS_EP_DIRECTION_IN |\n'
        '\t\t\t       XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\treturn XST_FAILURE;\n'
        '\t}\n\n'
        '\t/* Check that the requested reply length is not bigger than our',
        "CH9 sticky EP0 early gate",
    )
    source = replace_once(
        source,
        '\tif (SetupData->wLength > XUSBPS_REQ_REPLY_LEN) {\n'
        '\t\treturn;\n'
        '\t}',
        '\tif (SetupData->wLength > XUSBPS_REQ_REPLY_LEN) {\n'
        '\t\tXUsbPs_EpStall(InstancePtr, 0, XUSBPS_EP_DIRECTION_IN |\n'
        '\t\t\t       XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\treturn XST_FAILURE;\n'
        '\t}',
        "CH9 invalid length return status",
    )
    old = '\t\t\t\t\t\t/* Failure case needs to be handled */\n\t\t\t\t\t\tfor (;;);'
    count = source.count(old)
    if count != 5:
        raise ValueError(f"descriptor send failure anchor: expected five, found {count}")
    new = (
        '\t\t\t\t\t\t/* Return through the common EP0 stall path. */\n'
        '\t\t\t\t\t\t++XUsbPs_Ch9DescriptorSendFailures;\n'
        '\t\t\t\t\t\tStatus = XST_FAILURE;\n'
        '\t\t\t\t\t\tError = 1;'
    )
    source = source.replace(old, new)
    source = replace_once(
        source,
        '\t\tXUsbPs_EpStall(InstancePtr, 0, XUSBPS_EP_DIRECTION_IN |\n'
        '\t\t\t       XUSBPS_EP_DIRECTION_OUT);\n'
        '\t}\n'
        '}',
        '\t\tXUsbPs_EpStall(InstancePtr, 0, XUSBPS_EP_DIRECTION_IN |\n'
        '\t\t\t       XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\treturn XST_FAILURE;\n'
        '\t}\n'
        '\treturn Status;\n'
        '}',
        "CH9 error return after stall",
    )
    return source, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True,
                        help="usbps_v2_11 driver root with src/ and examples/")
    parser.add_argument("--out", type=Path, required=True,
                        help="fresh candidate workspace (overlay goes in usb_bounded_sdk/)")
    args = parser.parse_args()

    inputs: dict[str, bytes] = {}
    for name, spec in PINNED.items():
        path = args.source_root / spec["relative"]
        data = path.read_bytes()
        digest = sha256(data)
        if digest != spec["sha256"]:
            raise SystemExit(f"{name} source hash mismatch: {digest} ({path})")
        inputs[name] = data

    policy = POLICY.read_bytes()
    endpoint = patch_endpoint(inputs["endpoint"].decode("utf-8-sig"))
    ch9, loops = patch_ch9(inputs["ch9"].decode("utf-8-sig"))
    overlay = args.out / "usb_bounded_sdk" / "src"
    overlay.mkdir(parents=True, exist_ok=True)
    outputs = {
        "xusbps_endpoint.c": endpoint.encode("utf-8"),
        "xusbps_ch9.c": ch9.encode("utf-8"),
        "usb_bounded_sdk_policy.h": policy,
    }
    for name, data in outputs.items():
        (overlay / name).write_bytes(data)
    manifest = {
        "schema": 1,
        "source_root": str(args.source_root.resolve()),
        "inputs": {
            name: {"path": str((args.source_root / spec["relative"]).resolve()),
                   "sha256": spec["sha256"]}
            for name, spec in PINNED.items()
        },
        "outputs": {name: sha256(data) for name, data in outputs.items()},
        "patches": {
            "atdtw_poll_limit": 4096,
            "atdtw_failure": "clear-tripwire, flush+disable endpoint with bounded polls, preserve dTD/buffer ownership, return failure",
            "eprime_failure": "flush+disable endpoint with bounded polls, preserve dTD/buffer ownership, return failure",
            "sticky_fault": "per-controller endpoint fault latch blocks future queue writes and CH9 static reply reuse until explicit clear after controller reset and verified DMA quiescence",
            "descriptor_send_failure_loops_replaced": loops,
            "ch9_failure": "increment XUsbPs_Ch9DescriptorSendFailures, stall EP0, propagate XST_FAILURE to setup caller",
        },
    }
    manifest_path = args.out / "usb_bounded_sdk" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
