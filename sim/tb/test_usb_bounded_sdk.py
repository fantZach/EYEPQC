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
CH9_MOCK_C = ROOT / "sim" / "tb" / "test_usb_bounded_ch9_mock.c"
INTR_MOCK_C = ROOT / "sim" / "tb" / "test_usb_bounded_intr_mock.c"
TEST_TMP_ROOT = ROOT / "build" / "parallel_20261009" / "A"
NATIVE_GCC = r"E:\fpg\2026.1\tps\mingw\10.0.0\win64.o\nt\bin\gcc.exe"


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
    with tempfile.TemporaryDirectory(prefix="usb-bounded-sdk-", dir=TEST_TMP_ROOT) as td:
        overlay, manifest = generate(Path(td))
        assert manifest["inputs"]["endpoint"]["sha256"] == (
            "9331d7b0006f9738459ed0a4417db804ab1062a2b2fb709f98953ee843119575"
        )
        assert manifest["inputs"]["ch9"]["sha256"] == (
            "d30f2ec77c66f8323eea1e0dcb13391b168c7153ed116852665bca17daf68b88"
        )
        assert manifest["inputs"]["intr"]["sha256"] == (
            "51e3de9d30861450f2a6455c452a843da334ac24405e0a815b6d73c8c51ebe5a"
        )
        probe_output = Path(manifest["probe_output"]["path"])
        assert hashlib.sha256(probe_output.read_bytes()).hexdigest() == manifest["probe_output"]["sha256"]
        for name, expected in manifest["outputs"].items():
            assert hashlib.sha256((overlay / name).read_bytes()).hexdigest() == expected

        endpoint = (overlay / "xusbps_endpoint.c").read_text()
        ch9 = (overlay / "xusbps_ch9.c").read_text()
        intr = (overlay / "xusbps_intr.c").read_text()
        probe = probe_output.read_text()
        assert "XUsbPs_BoundedTripwireSample" in endpoint
        assert "XUsbPs_BoundedQuiesceInEndpoint" in endpoint
        assert endpoint.count("XUsbPs_BoundedQuiesceInEndpoint(") == 4
        assert endpoint.count("XUsbPs_BoundedMarkEndpointFaulted(InstancePtr, EpNum);") == 4
        assert "If a later ring slot is unexpectedly occupied" in endpoint
        assert "instead of returning with a partially published chain" in endpoint
        assert "dTDAttachBuffer" in endpoint
        assert "for (;;);" not in ch9
        assert ch9.count("++XUsbPs_Ch9DescriptorSendFailures;") == 5
        assert ch9.count("Status = XST_FAILURE;\n\t\t\t\t\t\tError = 1;") == 5
        assert "Status = XUsbPs_StdDevReq(InstancePtr, SetupData);" in ch9
        assert "return XST_FAILURE;" in ch9
        assert "XUsbPs_EpStall(InstancePtr, 0" in ch9
        first = ch9.index("static int XUsbPs_StdDevReq(XUsbPs *InstancePtr,")
        start = ch9.index("static int XUsbPs_StdDevReq(XUsbPs *InstancePtr,", first + 1)
        end = ch9.index("static int XUsbPs_HandleVendorReq(XUsbPs *InstancePtr,", start)
        std_req = ch9[start:end]
        assert "int Status = XST_SUCCESS;" in std_req
        assert std_req.count("XUsbPs_Ch9QueueEp0Reply(") == 14
        assert "XUsbPs_EpBufferSend(" not in std_req
        assert "XUsbPs_Ch9PrepareEp0ReplyBuffer" not in std_req
        assert "XUsbPs_BoundedPrepareEp0Setup" not in std_req
        assert "XUsbPs_Ch9OwnershipDiagnostics" in ch9
        assert "XUsbPs_BoundedPrepareEp0Setup(InstancePtr, &SetupData)" in intr
        assert "XUSBPS_EP_EVENT_SETUP_DATA_RECEIVED, &SetupData" in intr
        assert "XUsbPs_EpPrime(InstancePtr, 0U, XUSBPS_EP_DIRECTION_OUT)" in intr
        assert "EpCompl &= ~0x00010001U;" in intr
        assert "XUsbPs_BoundedEndpointIsFaulted(InstancePtr, 0U)" in intr
        setup_call = intr.index("XUsbPs_IntrHandleEp0Setup(InstancePtr) != XST_SUCCESS")
        completion_read = intr.index("XUSBPS_EPCOMPL_OFFSET", setup_call)
        tx_handler = intr.index("XUsbPs_IntrHandleTX(InstancePtr, EpCompl);", completion_read)
        assert setup_call < completion_read < tx_handler
        assert "XUsbPs_Ch9QueueEp0Reply(u, 0, buf, len, &status, &error)" in probe
        assert "XUsbPs_EpBufferSend(u, 0," not in probe
        assert "XUsbPs_EpGetSetupData(u, ep, &setup)" not in probe
        assert "line_pending = 0;" in probe
        set_line = probe.index("case 0x20: /* SET_LINE_CODING")
        assert "XUsbPs_EpPrime" not in probe[set_line:probe.index("case 0x21:", set_line)]
        get_setup = endpoint.index("int XUsbPs_EpGetSetupData(")
        setup_end = endpoint.index("/* EP0 OUT setup-safe rebuild", get_setup)
        setup_reader = endpoint[get_setup:setup_end]
        assert "for (Timeout = 0; Timeout < XUSBPS_BOUNDED_POLL_LIMIT; ++Timeout)" in setup_reader
        assert "Xil_DCacheInvalidateRange((unsigned int)Ep->dQH + 32U, 32U)" in setup_reader
        rebuild = endpoint[setup_end:]
        assert "Xil_DCacheInvalidateRange((unsigned int)Out->dQH + 32U, 32U)" in rebuild
        assert "Xil_DCacheFlushRange((unsigned int)Out->dQH, 32U)" in rebuild
        assert "XUsbPs_WritedQH(Out->dQH, 0x20U" not in rebuild
        assert "XUsbPs_WritedQH(Out->dQH, 0x28U" not in rebuild
        assert "sizeof(*Out->dQH) != XUSBPS_dQH_ALIGN" in rebuild
        assert "XUsbPs_ReconfigureEp(InstancePtr" in rebuild


def test_register_mock_compiles_and_runs_when_native_gcc_exists():
    gcc = NATIVE_GCC if Path(NATIVE_GCC).is_file() else shutil.which("gcc")
    if not Path(gcc).is_file():
        gcc = None
    with tempfile.TemporaryDirectory(prefix="usb-bounded-sdk-mock-", dir=TEST_TMP_ROOT) as td:
        temp = Path(td)
        overlay, _ = generate(temp)
        (temp / "xusbps_endpoint.h").write_text(
            "#define XUsbPs_dTDInvalidateCache(p) ((void)(p))\n"
            "#define XUsbPs_dTDIsActive(p) ((p)->active != 0U)\n",
            encoding="utf-8",
        )
        if gcc:
            exe = temp / "usb_bounded_sdk_mock.exe"
            subprocess.run(
                [gcc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                 "-I", str(overlay), "-I", str(temp), str(MOCK_C), "-o", str(exe)],
                check=True,
                capture_output=True,
                text=True,
            )
            completed = subprocess.run([str(exe)], check=True, capture_output=True, text=True)
            assert "PASS" in completed.stdout
        else:
            raise AssertionError("Native GCC is required to execute the register-mock harness")


def test_generated_intr_and_cdc_class_execute_with_host_stubs():
    gcc = NATIVE_GCC if Path(NATIVE_GCC).is_file() else shutil.which("gcc")
    assert Path(gcc).is_file(), "Native GCC is required to execute the generated USB integration mock"
    common = r'''#ifndef EYEPQC_CH9_MOCK_SDK_H
#define EYEPQC_CH9_MOCK_SDK_H
#include <stddef.h>
#include <stdint.h>
typedef uint8_t u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uintptr_t UINTPTR;
#define XST_SUCCESS 0
#define XST_FAILURE 1
#define XST_INVALID_PARAM 2
#define XST_USB_NO_DESC_AVAILABLE 27
#define XPAR_XUSBPS_0_BASEADDR 0x1000U
#define XINTERRUPT_DEFAULT_PRIORITY 0U
#define COUNTS_PER_SECOND 1000000U
typedef uint64_t XTime;
void XTime_GetTime(XTime *time_value);
#define XUSBPS_EP_DIRECTION_OUT 0x02U
#define XUSBPS_EP_DIRECTION_IN 0x01U
#define XUSBPS_EPFLUSH_TX_SHIFT 16U
#define XUSBPS_EPCR_TXE_MASK 0x00000004U
#define XUSBPS_EPCR_RXS_MASK 0x00000001U
#define XUSBPS_EPCR_TXS_MASK 0x00000002U
#define XUSBPS_EPCRn_OFFSET(n) (0x100U + (u32)(n) * 4U)
#define XUSBPS_EPCOMPL_OFFSET 0x0e0U
#define XUSBPS_CMD_OFFSET 0x080U
#define XUSBPS_CMD_ATDTW_MASK 0x4000U
#define XUSBPS_EPRDY_OFFSET 0x0c8U
#define XUSBPS_EPFLUSH_OFFSET 0x0e8U
#define XUSBPS_EPPRIME_OFFSET 0x200U
#define XUSBPS_PORTSCR1_OFFSET 0x300U
#define XUSBPS_EPSTAT_OFFSET 0x0c4U
#define XUSBPS_EPCR1_OFFSET 0x140U
#define XUSBPS_EPCR2_OFFSET 0x144U
#define XUSBPS_USBSTS_OFFSET 0x144U
#define XUSBPS_USBINTR_OFFSET 0x148U
#define XUSBPS_ISR_OFFSET 0x004U
#define XUSBPS_EPNAKISR_OFFSET 0x178U
#define XUSBPS_PORTSCR_PR_MASK 0x00000040U
#define XUSBPS_STATE_DEFAULT 0U
#define XUSBPS_EPFLUSH_TX_SHIFT 16U
#define XUSBPS_CMD_ATDTW_MASK 0x4000U
#define XUSBPS_EPCRn_OFFSET(n) (0x100U + (u32)(n) * 4U)
#define XUSBPS_EPCR_TXE_MASK 0x00000004U
#define XUSBPS_EPCR_RXS_MASK 0x00000001U
#define XUSBPS_EPCR_TXS_MASK 0x00000002U
#define XUSBPS_EPRDY_OFFSET 0x0c8U
#define XUSBPS_EP_OUT_MASK 0x00000fffU
#define XUSBPS_EP_IN_MASK 0x0fff0000U
#define XUSBPS_EP_ALL_MASK 0x0fff0fffU
#define XUSBPS_IXR_UI_MASK 0x00000001U
#define XUSBPS_IXR_UE_MASK 0x00000002U
#define XUSBPS_IXR_UR_MASK 0x00000040U
#define XUSBPS_IXR_PC_MASK 0x00000004U
#define XUSBPS_IXR_NAK_MASK 0x00010000U
#define XUSBPS_EP_EVENT_SETUP_DATA_RECEIVED 1U
#define XUSBPS_EP_EVENT_DATA_RX 2U
#define XUSBPS_EP_EVENT_DATA_TX 3U
#define XUSBPS_EP_TYPE_CONTROL 0U
#define XUSBPS_EP_TYPE_ISOCHRONOUS 1U
#define XUSBPS_EP_TYPE_BULK 2U
#define XUSBPS_EP_TYPE_INTERRUPT 3U
#define XUSBPS_EP_TYPE_NONE 4U
#define XUSBPS_EPCR_TXT_BULK_MASK 0x00000020U
#define XUSBPS_EPCR_RXT_BULK_MASK 0x00000040U
#define XUSBPS_EPCR_TXR_MASK 0x00000008U
#define XUSBPS_EPCR_RXR_MASK 0x00000010U
#define XUSBPS_EPCR_TXT_INTR_MASK 0x00000020U
#define XUSBPS_TIMEOUT_COUNTER 100U
#define XUSBPS_TIMEOUT_COUNTER 100U
typedef struct { uintptr_t BaseAddress; u32 IntrId, IntrParent; } XUsbPs_Config;
typedef struct XUsbPs_dTD { u32 nlp, token, active, bptr[5], userdata; struct XUsbPs_dTD *next; } XUsbPs_dTD;
#define XUSBPS_dQH_ALIGN 64U
typedef struct { u32 words[16]; } XUsbPs_dQH;
_Static_assert(sizeof(XUsbPs_dQH) == XUSBPS_dQH_ALIGN, "mock QH must match vendor 64-byte slot");
typedef void (*XUsbPs_EpHandlerFunc)(void *, u8, u8, void *);
typedef void (*XUsbPs_EpIsoHandlerFunc)(void *, u32, u32);
typedef struct {
    XUsbPs_dTD *dTDs, *dTDHead, *dTDTail; XUsbPs_dQH *dQH;
    XUsbPs_EpHandlerFunc HandlerFunc; void *HandlerRef;
    XUsbPs_EpIsoHandlerFunc HandlerIsoFunc;
    u8 *BufferPtr; u32 RequestedBytes, BytesTxed;
} XUsbPs_EpIn;
typedef struct {
    XUsbPs_dTD *dTDs, *dTDCurr; XUsbPs_dQH *dQH;
    XUsbPs_EpHandlerFunc HandlerFunc; void *HandlerRef;
    XUsbPs_EpIsoHandlerFunc HandlerIsoFunc;
    u8 *BufferPtr, *dTDBufs; u32 MemAlloted, RequestedBytes, BytesTxed;
} XUsbPs_EpOut;
typedef struct { XUsbPs_EpIn In; XUsbPs_EpOut Out; } XUsbPs_Ep;
typedef struct { u32 NumBufs, Type, BufSize, MaxPacketSize; } XUsbPs_EpCfgDir;
typedef struct { XUsbPs_EpCfgDir In, Out; } XUsbPs_EpConfig;
typedef struct {
    u32 NumEndpoints, DMAMemPhys; XUsbPs_EpConfig EpCfg[3]; XUsbPs_Ep Ep[3];
} XUsbPs_DeviceConfig;
typedef void (*XUsbPs_IntrHandlerFunc)(void *, u32);
typedef struct { u32 State; } XUsbPs_MockAppData;
typedef struct {
    XUsbPs_Config Config;
    XUsbPs_DeviceConfig DeviceConfig;
    XUsbPs_IntrHandlerFunc HandlerFunc; void *HandlerRef; u32 HandlerMask;
    void *UserDataPtr;
    XUsbPs_MockAppData *AppData;
    u8 CurrentAltSetting;
    u8 IsConfigDone;
} XUsbPs;
typedef struct {
    u8 bmRequestType;
    u8 bRequest;
    u16 wValue;
    u16 wIndex;
    u16 wLength;
} XUsbPs_SetupData;
int XUsbPs_EpBufferSend(XUsbPs *, u8, const u8 *, u32);
int XUsbPs_EpBufferReceive(XUsbPs *, u8, u8 **, u32 *, u32 *);
void XUsbPs_EpBufferRelease(u32);
void XUsbPs_EpStall(XUsbPs *, u8, u8);
void XUsbPs_SetDeviceAddress(XUsbPs *, u32);
u32 XUsbPs_ReadReg(uintptr_t, u32);
void XUsbPs_WriteReg(uintptr_t, u32, u32);
void XUsbPs_ClrBits(XUsbPs *, u32, u32);
void XUsbPs_SetBits(XUsbPs *, u32, u32);
int XUsbPs_EpPrime(XUsbPs *, u8, u8);
int XUsbPs_EpGetSetupData(XUsbPs *, int, XUsbPs_SetupData *);
int XUsbPs_ReconfigureEp(XUsbPs *, XUsbPs_DeviceConfig *, int, unsigned short, int);
void XUsbPs_EpEnable(XUsbPs *, u8, u8);
void XUsbPs_EpDisable(XUsbPs *, u8, u8);
void XUsbPs_EpUnStall(XUsbPs *, u8, u8);
int XUsbPs_EpSetHandler(XUsbPs *, u8, u8, XUsbPs_EpHandlerFunc, void *);
int XUsbPs_EpDataBufferReceive(XUsbPs *, u8, u8 *, u32);
int XUsbPs_EpGetData(XUsbPs *, u8, u32);
int XSetupInterruptSystem(XUsbPs *, void *, u32, u32, u32);
int XUsbPs_CfgInitialize(XUsbPs *, void *, uintptr_t);
XUsbPs_Config *XUsbPs_LookupConfig(u32);
int XUsbPs_ConfigureDevice(XUsbPs *, XUsbPs_DeviceConfig *);
int XUsbPs_IntrSetHandler(XUsbPs *, XUsbPs_IntrHandlerFunc, void *, u32);
void XUsbPs_IntrEnable(XUsbPs *, u32);
void XUsbPs_Start(XUsbPs *);
void Xil_DCacheFlushRange(uintptr_t, u32);
void Xil_DCacheInvalidateRange(uintptr_t, u32);
void xil_printf(const char *, ...);
int usleep(unsigned int);
#define XUSBPS_dTDTOKEN 0x04U
#define XUSBPS_dTDNLP 0x00U
#define XUSBPS_dTDUSERDATA 0x1cU
#define XUSBPS_dTDBPTR(n) (0x08U + (u32)(n) * 4U)
#define XUSBPS_dTDTOKEN_ACTIVE_MASK 0x80U
#define XUSBPS_dQHCPTR 0x04U
#define XUSBPS_dQHCFG 0x00U
#define XUSBPS_dQHdTDNLP 0x08U
#define XUSBPS_dQHdTDTOKEN 0x0cU
#define XUSBPS_dQHSUB0 0x28U
#define XUSBPS_dQHSUB1 0x2cU
#define XUsbPs_ReaddTD(td, id) ((id)==XUSBPS_dTDTOKEN?(td)->token:(id)==XUSBPS_dTDUSERDATA?(td)->userdata:(td)->bptr[((id)-8U)/4U])
#define XUsbPs_WritedTD(td, id, val) do { if ((id)==XUSBPS_dTDTOKEN) { (td)->token=(val); (td)->active=(((val)&XUSBPS_dTDTOKEN_ACTIVE_MASK)!=0U); } else if ((id)==XUSBPS_dTDUSERDATA) (td)->userdata=(val); else if ((id)==0U) (td)->next=(XUsbPs_dTD *)(uintptr_t)(val); else if ((id)>=8U && (id)<=24U) (td)->bptr[((id)-8U)/4U]=(val); } while (0)
#define XUsbPs_dTDGetNLP(td) ((td)->next)
#define XUsbPs_dTDIsActive(td) (((td)->token & XUSBPS_dTDTOKEN_ACTIVE_MASK) != 0U)
#define XUsbPs_WritedQH(qh, id, val) ((qh)->words[(id)/4U]=(u32)(uintptr_t)(val))
#define XUsbPs_ReaddQH(qh, id) ((qh)->words[(id)/4U])
void XUsbPs_dTDInvalidateCache(XUsbPs_dTD *);
void XUsbPs_dTDFlushCache(XUsbPs_dTD *);
void XUsbPs_dQHInvalidateCache(XUsbPs_dQH *);
void XUsbPs_dQHFlushCache(XUsbPs_dQH *);
void XUsbPs_EpFlush(XUsbPs *, u8, u8);
void XUsbPs_EpDisable(XUsbPs *, u8, u8);
void XUsbPs_EpEnable(XUsbPs *, u8, u8);
void XUsbPs_EpUnStall(XUsbPs *, u8, u8);
void XUsbPs_EpStall(XUsbPs *, u8, u8);
int XUsbPs_ReconfigureEp(XUsbPs *, XUsbPs_DeviceConfig *, int, unsigned short, int);
#define XUSBPS_REQ_TYPE_MASK 0x60U
#define XUSBPS_CMD_STDREQ 0x00U
#define XUSBPS_CMD_CLASSREQ 0x20U
#define XUSBPS_CMD_VENDREQ 0x40U
#define XUSBPS_REQ_REPLY_LEN 1024U
#define XUSBPS_ENDPOINT_HALT 0U
#define XUSBPS_TEST_MODE 2U
#define XUSBPS_REQ_GET_STATUS 0x00U
#define XUSBPS_REQ_CLEAR_FEATURE 0x01U
#define XUSBPS_REQ_SET_FEATURE 0x03U
#define XUSBPS_REQ_SET_ADDRESS 0x05U
#define XUSBPS_REQ_GET_DESCRIPTOR 0x06U
#define XUSBPS_REQ_GET_CONFIGURATION 0x08U
#define XUSBPS_REQ_SET_CONFIGURATION 0x09U
#define XUSBPS_REQ_GET_INTERFACE 0x0aU
#define XUSBPS_REQ_SET_INTERFACE 0x0bU
#define XUSBPS_REQ_SET_SEL 0x30U
#define XUSBPS_REQ_SET_ISOCH_DELAY 0x31U
#define XUSBPS_STATUS_MASK 0x03U
#define XUSBPS_STATUS_DEVICE 0x00U
#define XUSBPS_STATUS_INTERFACE 0x01U
#define XUSBPS_STATUS_ENDPOINT 0x02U
#define XUSBPS_TYPE_DEVICE_DESC 0x01U
#define XUSBPS_TYPE_CONFIG_DESC 0x02U
#define XUSBPS_TYPE_STRING_DESC 0x03U
#define XUSBPS_TYPE_DEVICE_QUALIFIER 0x06U
#define XUSBPS_TYPE_HID_DESC 0x21U
#define XUSBPS_TYPE_REPORT_DESC 0x22U
#define XUSBPS_TEST_J 1U
#define XUSBPS_TEST_K 2U
#define XUSBPS_TEST_SE0_NAK 3U
#define XUSBPS_TEST_PACKET 4U
#define XUSBPS_TEST_FORCE_ENABLE 5U
typedef struct { u8 CurrentConfig; } XUsbPs_Local;
#define ALIGNMENT_CACHELINE __attribute__((aligned(32)))
#define DCACHE_INVALIDATE_SIZE(a) (a)
#define Xil_AssertVoid(condition) do { if (!(condition)) return; } while (0)
#define Xil_AssertNonvoid(condition) do { if (!(condition)) return XST_FAILURE; } while (0)
#define Xil_AssertVoidAlways() ((void)0)
int XUsbPs_Ch9HandleSetupPacket(XUsbPs *, XUsbPs_SetupData *);
u8 XUsbPs_GetConfigDone(void *);
void XUsbPs_SetConfigDone(void *, u8);
void XUsbPs_ClassReq(XUsbPs *, XUsbPs_SetupData *);
u32 XUsbPs_Ch9SetupDevDescReply(u8 *, u32);
u32 XUsbPs_Ch9SetupCfgDescReply(u8 *, u32);
u32 XUsbPs_Ch9SetupStrDescReply(u8 *, u32, u8);
u32 XUsbPs_Ch9SetupHidDescReply(u8 *, u32);
u32 XUsbPs_Ch9SetupReportDescReply(u8 *, u32);
void XUsbPs_SetConfiguration(XUsbPs *, int);
void XUsbPs_SetConfigurationApp(XUsbPs *, XUsbPs_SetupData *);
void XUsbPs_SetInterfaceHandler(XUsbPs *, XUsbPs_SetupData *);
#endif
'''
    with tempfile.TemporaryDirectory(prefix="usb-bounded-ch9-mock-", dir=TEST_TMP_ROOT) as td:
        temp = Path(td)
        overlay, _ = generate(temp)
        stubs = temp / "stubs"
        stubs.mkdir()
        (stubs / "mock_sdk.h").write_text(common, encoding="utf-8")
        for header in ("xparameters.h", "xusbps.h", "xusbps_hw.h", "xusbps_endpoint.h", "xusbps_ch9.h",
                       "xil_printf.h", "xil_cache.h", "sleep.h", "xil_types.h", "xstatus.h",
                       "xinterrupt_wrap.h", "xiltimer.h", "xil_assert.h"):
            (stubs / header).write_text('#include "mock_sdk.h"\n', encoding="utf-8")
        exe = temp / "usb_bounded_intr_mock.exe"
        compiled = subprocess.run(
            [gcc, "-std=c11", "-w", "-ffunction-sections", "-fdata-sections",
             "-Wl,--gc-sections", "-DSDT", "-DUSB_LIBRARY", "-DG6_USB",
             "-I", str(overlay), "-I", str(temp), "-I", str(stubs),
             "-I", str(ROOT / "src/ps/include"), "-I", str(ROOT / "prj"),
             str(INTR_MOCK_C), "-o", str(exe)],
            capture_output=True, text=True,
        )
        assert compiled.returncode == 0, compiled.stdout + compiled.stderr
        try:
            completed = subprocess.run([str(exe)], capture_output=True, text=True, timeout=45)
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("Generated intr/CDC host harness exceeded 45 s; likely SDK ring-handler spin") from exc
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert "PASS" in completed.stdout


if __name__ == "__main__":
    test_hash_pinned_patch_and_ch9_failure_routing()
    test_register_mock_compiles_and_runs_when_native_gcc_exists()
    test_generated_intr_and_cdc_class_execute_with_host_stubs()
    print("USB_BOUNDED_SDK_TESTS_PASS 3/3")
