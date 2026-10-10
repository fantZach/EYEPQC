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
import re


PINNED = {
    "endpoint": {
        "relative": Path("src/xusbps_endpoint.c"),
        "sha256": "9331d7b0006f9738459ed0a4417db804ab1062a2b2fb709f98953ee843119575",
    },
    "ch9": {
        "relative": Path("examples/xusbps_ch9.c"),
        "sha256": "d30f2ec77c66f8323eea1e0dcb13391b168c7153ed116852665bca17daf68b88",
    },
    "intr": {
        "relative": Path("src/xusbps_intr.c"),
        "sha256": "51e3de9d30861450f2a6455c452a843da334ac24405e0a815b6d73c8c51ebe5a",
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
        '}\n\n'
        'void XUsbPs_BoundedClearEndpointFault(XUsbPs *InstancePtr, u8 EpNum)\n'
        '{\n'
        '\tu32 Slot;\n'
        '\tu32 Base = InstancePtr->Config.BaseAddress;\n'
        '\tfor (Slot = 0; Slot < XUSBPS_BOUNDED_FAULT_SLOTS; ++Slot) {\n'
        '\t\tif (XUsbPs_BoundedFaultBase[Slot] == Base) {\n'
        '\t\t\tXUsbPs_BoundedFaultMask[Slot] &= ~(1U << EpNum);\n'
        '\t\t\tif (XUsbPs_BoundedFaultMask[Slot] == 0U)\n'
        '\t\t\t\tXUsbPs_BoundedFaultBase[Slot] = 0U;\n'
        '\t\t\treturn;\n'
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
        '\t/* Fail closed before touching the ring when a previous bounded wait\n'
        '\t * latched this endpoint. For enabled non-control endpoints, also\n'
        '\t * refuse queueing while TXE is clear. EP0 ownership is separately\n'
        '\t * guarded by the setup-layer flush/prime protocol. */\n'
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
        '\t\t\t * Preserve every descriptor and buffer pointer if bounded\n'
        '\t\t\t * quiescence cannot be proven; retain sticky fail-closed state. */\n'
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
        '\t\t/* Tell the caller if we do not have any descriptors available. */\n'
        '\t\tif (XUsbPs_dTDIsActive(Ep->dTDHead)) {\n'
        '\t\t\treturn XST_USB_NO_DESC_AVAILABLE;\n'
        '\t\t}',
        '\t\t/* If a later ring slot is unexpectedly occupied, prior dTDs from\n'
        '\t\t * this request may already be active.  Quiesce and latch the endpoint\n'
        '\t\t * instead of returning with a partially published chain. */\n'
        '\t\tif (XUsbPs_dTDIsActive(Ep->dTDHead)) {\n'
        '\t\t\tXUsbPs_BoundedMarkEndpointFaulted(InstancePtr, EpNum);\n'
        '\t\t\t(void)XUsbPs_BoundedQuiesceInEndpoint(InstancePtr, EpNum, BitMask,\n'
        '\t\t\t\t\t\t\t  (1U << (EpNum + XUSBPS_EPFLUSH_TX_SHIFT)));\n'
        '\t\t\treturn XST_USB_NO_DESC_AVAILABLE;\n'
        '\t\t}',
        "mid-request busy dTD fail-closed path",
    )
    source = replace_once(
        source,
        '\t\tStatus = XUsbPs_dTDAttachBuffer(Ep->dTDHead, BufferPtr, Length);\n'
        '\t\tif (XST_SUCCESS != Status) {\n'
        '\t\t\treturn XST_FAILURE;\n'
        '\t\t}',
        '\t\tStatus = XUsbPs_dTDAttachBuffer(Ep->dTDHead, BufferPtr, Length);\n'
        '\t\tif (XST_SUCCESS != Status) {\n'
        '\t\t\tXUsbPs_BoundedMarkEndpointFaulted(InstancePtr, EpNum);\n'
        '\t\t\t(void)XUsbPs_BoundedQuiesceInEndpoint(InstancePtr, EpNum, BitMask,\n'
        '\t\t\t\t\t\t\t  (1U << (EpNum + XUSBPS_EPFLUSH_TX_SHIFT)));\n'
        '\t\t\treturn XST_FAILURE;\n'
        '\t\t}',
        "dTD attach fail-closed path",
    )
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
    source = replace_once(
        source,
        '\t\tXUsbPs_SetSetupTripwire(InstancePtr);\n\n'
        '\t\tXUsbPs_dQHInvalidateCache(Ep->dQH);\n\n'
        '\t\tData[0] = XUsbPs_ReaddQH(Ep->dQH, XUSBPS_dQHSUB0);',
        '\t\tXUsbPs_SetSetupTripwire(InstancePtr);\n\n'
        '\t\t/* SETUP bytes live in the aligned second 32-byte QH cache line.\n'
        '\t\t * Invalidate that complete line without a partial-line clean. */\n'
        '\t\tXil_DCacheInvalidateRange((unsigned int)Ep->dQH + 32U, 32U);\n\n'
        '\t\tData[0] = XUsbPs_ReaddQH(Ep->dQH, XUSBPS_dQHSUB0);',
        "EP0 SETUP cache-line invalidate",
    )
    source = replace_once(
        source,
        '\tdo {\n'
        '\t\t/* Arm the tripwire. The tripwire will tell us if a new setup\n'
        '\t\t * packet arrived (in which case the tripwire bit will be\n'
        '\t\t * cleared) while we were reading the buffer. If a new setup\n'
        '\t\t * packet arrived the buffer is corrupted and we continue\n'
        '\t\t * reading.\n'
        '\t\t */\n'
        '\t\tXUsbPs_SetSetupTripwire(InstancePtr);\n\n'
        '\t\t/* SETUP bytes live in the aligned second 32-byte QH cache line.\n'
        '\t\t * Invalidate that complete line without a partial-line clean. */\n'
        '\t\tXil_DCacheInvalidateRange((unsigned int)Ep->dQH + 32U, 32U);\n\n'
        '\t\tData[0] = XUsbPs_ReaddQH(Ep->dQH, XUSBPS_dQHSUB0);\n'
        '\t\tData[1] = XUsbPs_ReaddQH(Ep->dQH, XUSBPS_dQHSUB1);\n'
        '\t} while (FALSE == XUsbPs_SetupTripwireIsSet(InstancePtr));',
        '\tfor (Timeout = 0; Timeout < XUSBPS_BOUNDED_POLL_LIMIT; ++Timeout) {\n'
        '\t\tXUsbPs_SetSetupTripwire(InstancePtr);\n'
        '\t\t/* SETUP words share an aligned 32-byte cache line. */\n'
        '\t\tXil_DCacheInvalidateRange((unsigned int)Ep->dQH + 32U, 32U);\n'
        '\t\tData[0] = XUsbPs_ReaddQH(Ep->dQH, XUSBPS_dQHSUB0);\n'
        '\t\tData[1] = XUsbPs_ReaddQH(Ep->dQH, XUSBPS_dQHSUB1);\n'
        '\t\tif (XUsbPs_SetupTripwireIsSet(InstancePtr))\n'
        '\t\t\tbreak;\n'
        '\t}\n'
        '\tif (Timeout == XUSBPS_BOUNDED_POLL_LIMIT) {\n'
        '\t\tXUsbPs_ClrSetupTripwire(InstancePtr);\n'
        '\t\treturn XST_FAILURE;\n'
        '\t}',
        "bounded SDK SUTW read loop",
    )
    source = replace_once(
        source,
        '\tint Timeout;\n',
        '\tu32 Timeout;\n',
        "unsigned bounded SETUP poll counter",
    )
    source = replace_once(
        source,
        '\tEp = &InstancePtr->DeviceConfig.Ep[EpNum].Out;\n\n\n'
        '\t/* Get the data from the Queue Heads Setup buffer into local variables',
        '\tEp = &InstancePtr->DeviceConfig.Ep[EpNum].Out;\n'
        '\tif (Ep->dQH == NULL) return XST_FAILURE;\n\n'
        '\t/* Get the data from the Queue Heads Setup buffer into local variables',
        "setup reader null QH guard",
    )
    source += '''

/* EP0 OUT setup-safe rebuild. The SDK QH object is a 64-byte aligned slot;
 * hardware overlay fields occupy the first 48 bytes. Setup0/Setup1 at
 * 0x28/0x2c and BPTR4 at 0x20 share the second 32-byte cache line. Keep
 * that full line invalid while SDK ReconfigureEp flushes the full slot. */
int XUsbPs_BoundedRebuildEp0Out(XUsbPs *InstancePtr)
{
\tXUsbPs_EpOut *Out;
\tu32 Index;
\tu32 Field;
\tif (InstancePtr == NULL) return XST_FAILURE;
\tOut = &InstancePtr->DeviceConfig.Ep[0].Out;
\tif (Out->dQH == NULL || Out->dTDs == NULL || Out->dTDCurr == NULL ||
\t    InstancePtr->DeviceConfig.EpCfg[0].Out.NumBufs == 0U ||
\t    (((UINTPTR)Out->dQH) & 63U) != 0U ||
	    sizeof(*Out->dQH) != XUSBPS_dQH_ALIGN)
\t\treturn XST_FAILURE;
\tfor (Index = 0U; Index < InstancePtr->DeviceConfig.EpCfg[0].Out.NumBufs;
\t     ++Index) {
\t\tXUsbPs_dTD *Td = &Out->dTDs[Index];
\t\tXUsbPs_dTDInvalidateCache(Td);
\t\tXUsbPs_WritedTD(Td, XUSBPS_dTDTOKEN, 0U);
\t\tXUsbPs_WritedTD(Td, XUSBPS_dTDUSERDATA, 0U);
\t\tfor (Field = 0U; Field < 5U; ++Field)
\t\t\tXUsbPs_WritedTD(Td, XUSBPS_dTDBPTR(Field), 0U);
\t\tXUsbPs_dTDFlushCache(Td);
\t}
\t/* Both operations cover exactly one aligned 32-byte cache line; the
\t * second-line invalidate discards the old read-only setup snapshot. */
\tXil_DCacheInvalidateRange((unsigned int)Out->dQH + 32U, 32U);
\tXil_DCacheInvalidateRange((unsigned int)Out->dQH, 32U);
\tXUsbPs_WritedQH(Out->dQH, XUSBPS_dQHdTDTOKEN, 0U);
\tXUsbPs_WritedQH(Out->dQH, 0x04U, 0U);
\tXUsbPs_WritedQH(Out->dQH, 0x08U, 0U);
\tfor (Field = 0U; Field < 4U; ++Field)
\t\tXUsbPs_WritedQH(Out->dQH, 0x10U + Field * 4U, 0U);
\tXil_DCacheFlushRange((unsigned int)Out->dQH, 32U);
\t/* SDK resets dTDCurr, restores configured dTDBufs and ACTIVE/IOC, and
\t * writes only QH bytes 0..8 before its whole-object cache flush. The
\t * invalid setup line cannot write back stale SETUP data; BPTR4 at 0x20
\t * is left for controller overlay replacement from the new 64-byte dTD. */
\treturn XUsbPs_ReconfigureEp(InstancePtr, &InstancePtr->DeviceConfig, 0,
\t\t\t\t     XUSBPS_EP_DIRECTION_OUT, 0);
}
'''
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
        'volatile u32 XUsbPs_Ch9DescriptorSendFailures = 0U;\n'
        'volatile XUsbPs_Ch9OwnershipDiag XUsbPs_Ch9OwnershipDiagnostics = {0};',
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
        '\tint Status;\n\tint Error = 0;\n',
        '\tint Status = XST_SUCCESS;\n\tint Error = 0;\n',
        "CH9 default success status",
    )
    source = replace_once(
        source,
        '\t\t\tif (XST_SUCCESS == Status) {\n'
        '\t\t\t\t/* Return the buffer. */\n'
        '\t\t\t\tXUsbPs_EpBufferRelease(Handler);\n'
        '\t\t\t}\n\n'
        '\t\t\tbreak;\n\n'
        '\t\tcase XUSBPS_REQ_SET_ISOCH_DELAY:',
        '\t\t\tif (XST_SUCCESS == Status) {\n'
        '\t\t\t\t/* Return the buffer. */\n'
        '\t\t\t\tXUsbPs_EpBufferRelease(Handler);\n'
        '\t\t\t} else {\n'
        '\t\t\t\tStatus = XST_FAILURE;\n'
        '\t\t\t\tError = 1;\n'
        '\t\t\t}\n\n'
        '\t\t\tbreak;\n\n'
        '\t\tcase XUSBPS_REQ_SET_ISOCH_DELAY:',
        "CH9 SET_SEL receive failure stall routing",
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
    handler_signature = 'static int XUsbPs_StdDevReq(XUsbPs *InstancePtr,'
    first_signature = source.index(handler_signature)
    start = source.index(handler_signature, first_signature + len(handler_signature))
    end = source.index('static int XUsbPs_HandleVendorReq(XUsbPs *InstancePtr,', start)
    request_handler = source[start:end]
    send_calls = re.findall(r'XUsbPs_EpBufferSend\((.*?)\);', request_handler, re.DOTALL)
    if len(send_calls) < 10:
        raise ValueError(f"CH9 EP0 send anchors: expected at least ten, found {len(send_calls)}")
    request_handler = re.sub(
        r'XUsbPs_EpBufferSend\((.*?)\);',
        lambda match: 'XUsbPs_Ch9QueueEp0Reply(' + match.group(1) +
                      ', &Status, &Error);',
        request_handler,
        flags=re.DOTALL,
    )
    source = source[:start] + request_handler + source[end:]
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
    handler_signature = 'static int XUsbPs_StdDevReq(XUsbPs *InstancePtr,'
    first_signature = source.index(handler_signature)
    start = source.index(handler_signature, first_signature + len(handler_signature))
    end = source.index('static int XUsbPs_HandleVendorReq(XUsbPs *InstancePtr,', start)
    if 'XUsbPs_EpBufferSend(' in source[start:end]:
        raise ValueError("CH9 EP0 send bypasses bounded status/error wrapper")
    return source, count


def patch_intr(source: str) -> str:
    source = replace_once(
        source,
        '#include "xusbps.h"\n#include "xusbps_endpoint.h"',
        '#include "xusbps.h"\n#include "xusbps_endpoint.h"\n'
        '#include "usb_bounded_sdk_policy.h"',
        "interrupt policy include",
    )
    source = replace_once(
        source,
        'static void XUsbPs_IntrHandleEp0Setup(XUsbPs *InstancePtr);',
        'static int XUsbPs_IntrHandleEp0Setup(XUsbPs *InstancePtr);',
        "interrupt setup handler status prototype",
    )
    old = (
        '\t\tif (EpStat & 0x0001) {\n'
        '\t\t\t/* Handle the setup packet */\n'
        '\t\t\tXUsbPs_IntrHandleEp0Setup(InstancePtr);\n\n'
        '\t\t\t/* Re-Prime the endpoint.\n'
        '\t\t\t * Endpoint is de-primed if a setup packet comes in.\n'
        '\t\t\t */\n'
        '\t\t\tXUsbPs_EpPrime(InstancePtr, 0, XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\t}\n\n'
        '\t\t/* Check for RX and TX complete interrupts. */\n'
        '\t\tEpCompl = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,\n'
        '\t\t\t\t\t XUSBPS_EPCOMPL_OFFSET);\n\n\n'
        '\t\t/* ACK the complete interrupts. */\n'
        '\t\tXUsbPs_WriteReg(InstancePtr->Config.BaseAddress,\n'
        '\t\t\t\tXUSBPS_EPCOMPL_OFFSET, EpCompl);'
    )
    new = (
        '\t\t{\n'
        '\t\t\tint SetupReady = !XUsbPs_BoundedEndpointIsFaulted(InstancePtr, 0U);\n'
        '\t\t\tif (EpStat & 0x0001) {\n'
        '\t\t\t\t/* This helper snapshots SETUP, cancels/rebuilds both EP0\n'
        '\t\t\t\t * directions, dispatches once, then primes OUT once. */\n'
        '\t\t\t\tif (XUsbPs_IntrHandleEp0Setup(InstancePtr) != XST_SUCCESS)\n'
        '\t\t\t\t\tSetupReady = 0;\n'
        '\t\t\t\telse\n'
        '\t\t\t\t\tSetupReady = 1;\n'
        '\t\t\t}\n\n'
        '\t\t\t/* Check for RX and TX complete interrupts. */\n'
        '\t\t\tEpCompl = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,\n'
        '\t\t\t\t\t\t XUSBPS_EPCOMPL_OFFSET);\n'
        '\t\t\t/* W1C the sampled events, then suppress EP0 dispatch locally.\n'
        '\t\t\t * A failed gate must not leave a level-triggered IRQ storm. */\n'
        '\t\t\tXUsbPs_WriteReg(InstancePtr->Config.BaseAddress,\n'
        '\t\t\t\t\tXUSBPS_EPCOMPL_OFFSET, EpCompl);\n'
        '\t\t\tif (!SetupReady)\n'
        '\t\t\t\tEpCompl &= ~0x00010001U;\n'
        '\t\t}'
    )
    source = replace_once(source, old, new, "bounded EP0 interrupt dispatch gate")
    source = replace_once(
        source,
        'static void XUsbPs_IntrHandleEp0Setup(XUsbPs *InstancePtr)\n{\n\n'
        '\tXUsbPs_EpOut\t*Ep;\n\n'
        '\t/* Notify the user. */\n'
        '\tEp = &InstancePtr->DeviceConfig.Ep[0].Out;\n\n'
        '\tif (Ep->HandlerFunc) {\n'
        '\t\tEp->HandlerFunc(Ep->HandlerRef, 0,\n'
        '\t\t\t\tXUSBPS_EP_EVENT_SETUP_DATA_RECEIVED, NULL);\n'
        '\t}\n'
        '}',
        'static int XUsbPs_IntrHandleEp0Setup(XUsbPs *InstancePtr)\n{\n'
        '\tXUsbPs_EpOut *Ep = &InstancePtr->DeviceConfig.Ep[0].Out;\n'
        '\tXUsbPs_SetupData SetupData;\n\n'
        '\tif (XUsbPs_BoundedPrepareEp0Setup(InstancePtr, &SetupData) !=\n'
        '\t    XST_SUCCESS)\n'
        '\t\treturn XST_FAILURE;\n'
        '\t/* A SETUP arriving after the bounded rebuild but before dispatch\n'
        '\t * supersedes the snapshot. SUTW copies the newest QH setup words. */\n'
        '\tif (XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,\n'
        '\t\t\t    XUSBPS_EPSTAT_OFFSET) & 0x0001U) {\n'
        '\t\tif (XUsbPs_EpGetSetupData(InstancePtr, 0, &SetupData) !=\n'
        '\t\t    XST_SUCCESS) {\n'
        '\t\t\tXUsbPs_BoundedMarkEndpointFaulted(InstancePtr, 0U);\n'
        '\t\t\tXUsbPs_EpDisable(InstancePtr, 0U,\n'
        '\t\t\t\t\t XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\t\tXUsbPs_EpStall(InstancePtr, 0U,\n'
        '\t\t\t\t\t XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\t\treturn XST_FAILURE;\n'
        '\t\t}\n'
        '\t}\n'
        '\tif (Ep->HandlerFunc) {\n'
        '\t\tEp->HandlerFunc(Ep->HandlerRef, 0,\n'
        '\t\t\t\tXUSBPS_EP_EVENT_SETUP_DATA_RECEIVED, &SetupData);\n'
        '\t}\n'
        '\tif (XUsbPs_BoundedEndpointIsFaulted(InstancePtr, 0U) ||\n'
        '\t    XUsbPs_EpPrime(InstancePtr, 0U, XUSBPS_EP_DIRECTION_OUT) !=\n'
        '\t    XST_SUCCESS) {\n'
        '\t\tXUsbPs_BoundedMarkEndpointFaulted(InstancePtr, 0U);\n'
        '\t\tXUsbPs_EpDisable(InstancePtr, 0U,\n'
        '\t\t\t\t XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\tXUsbPs_EpStall(InstancePtr, 0U,\n'
        '\t\t\t\t XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);\n'
        '\t\treturn XST_FAILURE;\n'
        '\t}\n'
        '\treturn XST_SUCCESS;\n'
        '}',
        "interrupt setup snapshot callback and single OUT prime",
    )
    return source


def patch_probe(source: str) -> str:
    source = replace_once(
        source,
        '#include "usb_recovery.h"',
        '#include "usb_recovery.h"\n#include "usb_bounded_sdk_policy.h"',
        "probe bounded EP0 policy include",
    )
    source = replace_once(
        source,
        '__asm__ volatile("dmb sy" ::: "memory");',
        '#if defined(__arm__) || defined(__aarch64__)\n'
        '    __asm__ volatile("dmb sy" ::: "memory");\n'
        '#else\n'
        '    __asm__ volatile("" ::: "memory");\n'
        '#endif',
        "probe host-testable data barrier",
    )
    start = source.index('void XUsbPs_ClassReq(XUsbPs *u, XUsbPs_SetupData *s) {')
    end = source.index('static void ep1_in(', start)
    old = source[start:end]
    if old.count('static void ep0(') != 1:
        raise ValueError("probe EP0/class handler block changed")
    new = '''static int probe_ep0_send(XUsbPs *u, const u8 *buf, u32 len) {
    int status = XST_SUCCESS, error = 0;
    XUsbPs_Ch9QueueEp0Reply(u, 0, buf, len, &status, &error);
    if (error) XUsbPs_EpStall(u, 0, XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
    return status;
}

void XUsbPs_ClassReq(XUsbPs *u, XUsbPs_SetupData *s) {
    switch (s->bRequest) {
    case 0x20: /* SET_LINE_CODING; EP0 OUT is primed once by the SDK overlay. */
        if (s->wLength == 7) line_pending = 1;
        else XUsbPs_EpStall(u, 0, XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
        return;
    case 0x21: /* GET_LINE_CODING */
        (void)probe_ep0_send(u, line_coding, 7);
        return;
    case 0x22: /* SET_CONTROL_LINE_STATE */
        if (!((s->wValue & 1) && dtr)) ++connection_epoch;
        dtr = s->wValue & 1;
        mode = 0;
        test_epoch = test_epoch_bytes = 0;
#ifdef G6_USB
        rx_reset();
#endif
        jpeg_receiving = jpeg_ready = jpeg_bad = 0;
        if (!dtr && configured) {
            if (eye_usb_rearm_data(u, 0)) { ++usb_recovery_failures; configured = 0; }
            tx_ready = 1;
        }
        if (dtr) block_no = 0;
        (void)probe_ep0_send(u, NULL, 0);
        return;
    case 0x23: /* SEND_BREAK */
        (void)probe_ep0_send(u, NULL, 0);
        return;
    default:
        XUsbPs_EpStall(u, 0, XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
        return;
    }
}

static void ep0(void *ref, u8 ep, u8 event, void *data) {
    XUsbPs *u = ref;
    if (event == XUSBPS_EP_EVENT_SETUP_DATA_RECEIVED) {
        line_pending = 0;
        if (data != NULL)
            XUsbPs_Ch9HandleSetupPacket(u, (XUsbPs_SetupData *)data);
    } else if (event == XUSBPS_EP_EVENT_DATA_RX) {
        u8 *buf; u32 len, handle;
        if (XUsbPs_EpBufferReceive(u, ep, &buf, &len, &handle) == XST_SUCCESS) {
            if (line_pending) {
                if (len == 7) {
                    Xil_DCacheInvalidateRange((UINTPTR)buf, 32);
                    memcpy(line_coding, buf, 7);
                    line_pending = 0;
                    (void)probe_ep0_send(u, NULL, 0);
                } else {
                    line_pending = 0;
                    XUsbPs_EpStall(u, 0, XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
                }
            }
            XUsbPs_EpBufferRelease(handle);
        }
    }
}
'''
    source = source[:start] + new + source[end:]
    if 'XUsbPs_EpBufferSend(u, 0,' in source:
        raise ValueError("probe class EP0 send bypasses bounded wrapper")
    if 'XUsbPs_EpGetSetupData(u, ep, &setup)' in source:
        raise ValueError("probe setup callback rereads QH instead of using intr snapshot")
    return source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True,
                        help="usbps_v2_11 driver root with src/ and examples/")
    parser.add_argument("--out", type=Path, required=True,
                        help="fresh candidate workspace (overlay goes in usb_bounded_sdk/)")
    args = parser.parse_args()

    overlay_root = args.out / "usb_bounded_sdk"
    if overlay_root.exists() and any(overlay_root.iterdir()):
        raise SystemExit(f"refusing to overwrite existing overlay: {overlay_root}")

    inputs: dict[str, bytes] = {}
    for name, spec in PINNED.items():
        path = args.source_root / spec["relative"]
        data = path.read_bytes()
        digest = sha256(data)
        if digest != spec["sha256"]:
            raise SystemExit(f"{name} source hash mismatch: {digest} ({path})")
        inputs[name] = data

    policy = POLICY.read_bytes()
    probe_path = Path(__file__).resolve().parent / "usb_probe.c"
    probe_input = probe_path.read_bytes()
    probe_hash = sha256(probe_input)
    endpoint = patch_endpoint(inputs["endpoint"].decode("utf-8-sig"))
    ch9, loops = patch_ch9(inputs["ch9"].decode("utf-8-sig"))
    intr = patch_intr(inputs["intr"].decode("utf-8-sig"))
    probe = patch_probe(probe_input.decode("utf-8-sig"))
    overlay = args.out / "usb_bounded_sdk" / "src"
    overlay.mkdir(parents=True, exist_ok=True)
    outputs = {
        "xusbps_endpoint.c": endpoint.encode("utf-8"),
        "xusbps_ch9.c": ch9.encode("utf-8"),
        "xusbps_intr.c": intr.encode("utf-8"),
        "usb_bounded_sdk_policy.h": policy,
    }
    for name, data in outputs.items():
        (overlay / name).write_bytes(data)
    probe_output = args.out / "usb_probe_bounded_generated.c"
    probe_output.write_bytes(probe.encode("utf-8"))
    manifest = {
        "schema": 1,
        "source_root": str(args.source_root.resolve()),
        "inputs": {
            name: {"path": str((args.source_root / spec["relative"]).resolve()),
                   "sha256": spec["sha256"]}
            for name, spec in PINNED.items()
        },
        "outputs": {name: sha256(data) for name, data in outputs.items()},
        "probe_input": {"path": str(probe_path.resolve()), "sha256": probe_hash},
        "probe_output": {"path": str(probe_output.resolve()),
                         "sha256": sha256(probe_output.read_bytes())},
        "patches": {
            "atdtw_poll_limit": 4096,
            "atdtw_failure": "clear-tripwire, flush+disable endpoint with bounded polls, preserve dTD/buffer ownership, return failure",
            "partial_queue_failure": "mid-request busy dTD and dTD attach errors use sticky fault plus bounded flush/disable; preserve published queue ownership",
            "eprime_failure": "flush+disable endpoint with bounded polls, preserve dTD/buffer ownership, return failure",
            "sticky_fault": "per-controller endpoint fault latch blocks future queue writes and CH9 static reply reuse; clear-all is reserved for full controller reset plus global DMA-idle proof, while per-endpoint clear requires successful bounded endpoint quiesce, dTD/QH ring rebuild, and endpoint-local ownership proof",
            "descriptor_send_failure_loops_replaced": loops,
            "ch9_failure": "increment XUsbPs_Ch9DescriptorSendFailures, stall EP0, propagate XST_FAILURE to setup caller",
            "ep0_setup_gate": "SDK intr snapshots setup with SUTW, requires bounded FLUSH deassertion and PRIME clear for both directions, acknowledges old completions, rebuilds both rings, rereads latest SUTW setup, invokes callback with snapshot, then primes OUT once; failures skip callback and EP0 completion dispatch. EP0 disable is best-effort only because EPCR0 TXE/RXE are read-only.",
            "ep0_qh_cache": "Vendor XUsbPs_dQH is a 64-byte aligned slot; hardware overlay uses first 48 bytes. BPTR4 at 0x20 and Setup0/Setup1 at 0x28/0x2c share the second 32-byte cache line. Invalidate that full line before SDK whole-slot ReconfigureEp flush, never write it in CPU cleanup, write/flush only first 32 bytes; host sentinel verifies 0x20 and setup bytes survive.",
            "cdc_class_ep0": "SETUP uses SDK-provided snapshot; SET_LINE_CODING defers pending state to current SETUP and uses common single OUT prime; every class EP0 IN reply uses sticky failure/stall wrapper",
        },
    }
    manifest_path = args.out / "usb_bounded_sdk" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
