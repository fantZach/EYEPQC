"""Native state-flow tests for usb_recovery.h with a minimal fake XUsbPs API.

These tests exercise the application helper and its call ordering only. They do
not emulate the USB controller, DMA, or AMD's USBPS driver implementation.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


FAKE_XUSBPS_H = r"""
#ifndef TEST_FAKE_XUSBPS_H
#define TEST_FAKE_XUSBPS_H
#include <stdint.h>
#include <stddef.h>
typedef uint32_t u32;
typedef uintptr_t UINTPTR;
typedef struct { uint32_t next, token, overlay[6]; } XUsbPs_dQH;
typedef struct { uint32_t next, token; uintptr_t buffer; uint32_t error; } XUsbPs_dTD;
typedef struct {
    XUsbPs_dQH *dQH;
    XUsbPs_dTD *dTDs;
    XUsbPs_dTD *dTDHead, *dTDTail;
    void *BufferPtr;
    uint32_t RequestedBytes, BytesTxed;
} XUsbPs_EpIn;
typedef struct {
    XUsbPs_dQH *dQH;
    XUsbPs_dTD *dTDs, *dTDCurr;
    void *BufferPtr;
    uint32_t MemAlloted, RequestedBytes, BytesTxed;
} XUsbPs_EpOut;
typedef struct { XUsbPs_EpOut Out; XUsbPs_EpIn In; } XUsbPs_Endpoint;
typedef struct { uint32_t NumBufs; } XUsbPs_DirCfg;
typedef struct { XUsbPs_DirCfg Out, In; } XUsbPs_EpCfg;
typedef struct {
    unsigned NumEndpoints;
    XUsbPs_Endpoint Ep[3];
    XUsbPs_EpCfg EpCfg[3];
} XUsbPs_DeviceConfig;
typedef struct { uintptr_t BaseAddress; } XUsbPs_Config;
typedef struct { XUsbPs_DeviceConfig DeviceConfig; XUsbPs_Config Config; } XUsbPs;

#define XUSBPS_EP_DIRECTION_OUT 1U
#define XUSBPS_EP_DIRECTION_IN  2U
#define XUSBPS_EPFLUSH_OFFSET   0x100U
#define XUSBPS_EPCOMPL_OFFSET   0x104U
#define XUSBPS_EPCR1_OFFSET     0x108U
#define XUSBPS_EPCR2_OFFSET     0x10cU
#define XUSBPS_EPPRIME_OFFSET   0x110U
#define XUSBPS_EPCR_TXT_BULK_MASK 0x1U
#define XUSBPS_EPCR_RXT_BULK_MASK 0x2U
#define XUSBPS_EPCR_TXR_MASK      0x4U
#define XUSBPS_EPCR_RXR_MASK      0x8U
#define XUSBPS_EPCR_TXT_INTR_MASK 0x10U
#define XUSBPS_dQHdTDNLP 0U
#define XST_SUCCESS 0
#define XST_FAILURE 1
#define XST_USB_NO_DESC_AVAILABLE 2
#define TEST_DTD_ACTIVE 0x80000000U
#define TEST_DTD_TERMINATE 0x1U

void Xil_DCacheInvalidateRange(UINTPTR address, uint32_t length);
void Xil_DCacheFlushRange(UINTPTR address, uint32_t length);
int XUsbPs_ReconfigureEp(XUsbPs *u, XUsbPs_DeviceConfig *c, int ep,
                         unsigned short dir, int direction_changed);
void XUsbPs_WritedQH(XUsbPs_dQH *qh, unsigned field, uint32_t value);
void XUsbPs_dQHFlushCache(XUsbPs_dQH *qh);
void XUsbPs_EpDisable(XUsbPs *u, unsigned ep, unsigned dir);
void XUsbPs_EpEnable(XUsbPs *u, unsigned ep, unsigned dir);
void XUsbPs_SetBits(XUsbPs *u, unsigned offset, uint32_t bits);
void XUsbPs_WriteReg(uintptr_t base, unsigned offset, uint32_t value);
uint32_t XUsbPs_ReadReg(uintptr_t base, unsigned offset);
int XUsbPs_EpPrime(XUsbPs *u, unsigned ep, unsigned dir);

#endif
"""


FAKE_XUSBPS_ENDPOINT_H = r"""
#ifndef TEST_FAKE_XUSBPS_ENDPOINT_H
#define TEST_FAKE_XUSBPS_ENDPOINT_H
#include "xusbps.h"
int XUsbPs_ReconfigureEp(XUsbPs *u, XUsbPs_DeviceConfig *c, int ep,
                         unsigned short dir, int direction_changed);
#endif
"""


HARNESS_C = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "usb_recovery.h"

#define FLUSH_MASK ((1U << 1) | (1U << 17) | (1U << 18))
#define TD_ACTIVE TEST_DTD_ACTIVE
#define TD_TERMINATE TEST_DTD_TERMINATE

static XUsbPs device;
static XUsbPs_dQH qh[3][2];
static XUsbPs_dTD td[3][2][4];
static int flush_stuck, prime_stuck, reconfigure_fail_at, reconfigure_calls;
static unsigned disable_calls, enable_calls, prime_calls, zeroed_on_reconfigure;
static unsigned completion_clear_calls;
static uint32_t flush_value;
static uint32_t ep1_bits, ep2_bits;

void Xil_DCacheInvalidateRange(UINTPTR address, uint32_t length) {
    (void)address; (void)length;
}
void Xil_DCacheFlushRange(UINTPTR address, uint32_t length) {
    (void)address; (void)length;
}
void XUsbPs_WritedQH(XUsbPs_dQH *p, unsigned field, uint32_t value) {
    assert(field == XUSBPS_dQHdTDNLP);
    p->next = value;
}
void XUsbPs_dQHFlushCache(XUsbPs_dQH *p) { (void)p; }
void XUsbPs_EpDisable(XUsbPs *u, unsigned ep, unsigned dir) {
    (void)u; assert((ep == 1 && (dir == XUSBPS_EP_DIRECTION_IN || dir == XUSBPS_EP_DIRECTION_OUT)) ||
                   (ep == 2 && dir == XUSBPS_EP_DIRECTION_IN));
    ++disable_calls;
}
void XUsbPs_EpEnable(XUsbPs *u, unsigned ep, unsigned dir) {
    (void)u; assert((ep == 1 && (dir == XUSBPS_EP_DIRECTION_IN || dir == XUSBPS_EP_DIRECTION_OUT)) ||
                   (ep == 2 && dir == XUSBPS_EP_DIRECTION_IN));
    ++enable_calls;
}
void XUsbPs_SetBits(XUsbPs *u, unsigned offset, uint32_t bits) {
    (void)u;
    if (offset == XUSBPS_EPCR1_OFFSET) ep1_bits |= bits;
    else if (offset == XUSBPS_EPCR2_OFFSET) ep2_bits |= bits;
    else assert(0);
}
void XUsbPs_WriteReg(uintptr_t base, unsigned offset, uint32_t value) {
    (void)base;
    if (offset == XUSBPS_EPFLUSH_OFFSET) flush_value = value;
    else if (offset == XUSBPS_EPCOMPL_OFFSET) ++completion_clear_calls;
}
uint32_t XUsbPs_ReadReg(uintptr_t base, unsigned offset) {
    (void)base;
    if (offset == XUSBPS_EPFLUSH_OFFSET) return flush_stuck ? flush_value : 0;
    if (offset == XUSBPS_EPPRIME_OFFSET) return prime_stuck ? (1U << 17) : 0;
    return 0;
}
int XUsbPs_EpPrime(XUsbPs *u, unsigned ep, unsigned dir) {
    (void)u; assert(ep == 1 && dir == XUSBPS_EP_DIRECTION_OUT);
    ++prime_calls;
    return XST_SUCCESS;
}

static int bytes_are_zero(const void *p, size_t n) {
    const unsigned char *b = p;
    for (size_t i = 0; i < n; ++i) if (b[i]) return 0;
    return 1;
}

int XUsbPs_ReconfigureEp(XUsbPs *u, XUsbPs_DeviceConfig *c, int ep,
                         unsigned short dir, int direction_changed) {
    assert(u == &device && c == &device.DeviceConfig && direction_changed == 0);
    ++reconfigure_calls;
    XUsbPs_dQH *q = dir == XUSBPS_EP_DIRECTION_IN ? c->Ep[ep].In.dQH : c->Ep[ep].Out.dQH;
    XUsbPs_dTD *d = dir == XUSBPS_EP_DIRECTION_IN ? c->Ep[ep].In.dTDs : c->Ep[ep].Out.dTDs;
    unsigned n = dir == XUSBPS_EP_DIRECTION_IN ? c->EpCfg[ep].In.NumBufs : c->EpCfg[ep].Out.NumBufs;
    if (bytes_are_zero(q, sizeof(*q)) && bytes_are_zero(d, n * sizeof(*d))) ++zeroed_on_reconfigure;
    if (reconfigure_fail_at == reconfigure_calls) return XST_FAILURE;
    if (dir == XUSBPS_EP_DIRECTION_IN) {
        c->Ep[ep].In.dTDHead = c->Ep[ep].In.dTDs;
        c->Ep[ep].In.dTDTail = c->Ep[ep].In.dTDs;
        for (unsigned i = 0; i < n; ++i) {
            d[i].next = (uint32_t)(uintptr_t)&d[(i + 1) % n];
            d[i].token = TD_TERMINATE;
        }
    } else {
        c->Ep[ep].Out.dTDCurr = c->Ep[ep].Out.dTDs;
        for (unsigned i = 0; i < n; ++i) {
            d[i].next = (uint32_t)(uintptr_t)&d[(i + 1) % n];
            d[i].token = TD_ACTIVE;
        }
    }
    q->next = (uint32_t)(uintptr_t)d;
    q->token = 0;
    return XST_SUCCESS;
}

static void setup_case(void) {
    memset(&device, 0, sizeof(device));
    memset(qh, 0, sizeof(qh));
    memset(td, 0, sizeof(td));
    device.DeviceConfig.NumEndpoints = 3;
    for (unsigned ep = 0; ep < 3; ++ep) {
        device.DeviceConfig.Ep[ep].Out.dQH = &qh[ep][0];
        device.DeviceConfig.Ep[ep].In.dQH = &qh[ep][1];
        device.DeviceConfig.Ep[ep].Out.dTDs = td[ep][0];
        device.DeviceConfig.Ep[ep].Out.dTDCurr = td[ep][0];
        device.DeviceConfig.Ep[ep].In.dTDs = td[ep][1];
        device.DeviceConfig.Ep[ep].In.dTDHead = td[ep][1];
        device.DeviceConfig.Ep[ep].In.dTDTail = td[ep][1];
        device.DeviceConfig.EpCfg[ep].Out.NumBufs = 3;
        device.DeviceConfig.EpCfg[ep].In.NumBufs = 3;
    }
    device.Config.BaseAddress = 0x1000;
    flush_stuck = prime_stuck = reconfigure_fail_at = reconfigure_calls = 0;
    disable_calls = enable_calls = prime_calls = zeroed_on_reconfigure = 0;
    completion_clear_calls = 0;
    flush_value = 0;
    ep1_bits = ep2_bits = 0;
}

static void seed_stale_queues(void) {
    for (unsigned i = 0; i < 3; ++i) {
        qh[1][0].overlay[i] = 0xdead0000U + i;
        qh[1][1].overlay[i] = 0xbeef0000U + i;
        qh[2][1].overlay[i] = 0xcafe0000U + i;
    }
    qh[1][0].token = 0xdeadbeefU;
    qh[1][1].token = 0xbad0c0deU;
    qh[2][1].token = 0xfeedfaceU;
    for (unsigned ep = 1; ep <= 2; ++ep) {
        unsigned dirs = ep == 1 ? 2 : 1;
        for (unsigned k = 0; k < dirs; ++k) {
            unsigned dir = ep == 1 ? k : 1;
            XUsbPs_dTD *base = td[ep][dir];
            for (unsigned i = 0; i < 3; ++i) {
                base[i].next = 0xa0000000U + i;
                base[i].token = TD_ACTIVE | 0x400000U | (i << 8); /* active + error/residual */
                base[i].buffer = 0x12340000U + i;
                base[i].error = 0x55aa0000U + i;
            }
        }
    }
    device.DeviceConfig.Ep[1].In.dTDHead = &td[1][1][2];
    device.DeviceConfig.Ep[1].In.dTDTail = &td[1][1][1];
    device.DeviceConfig.Ep[1].Out.dTDCurr = &td[1][0][2];
}

static void test_success_rebuilds_all_data_queues(void) {
    setup_case(); seed_stale_queues();
    assert(eye_usb_rearm_data(&device, 1) == 0);
    assert(disable_calls == 3 && reconfigure_calls == 3);
    assert(zeroed_on_reconfigure == 3);
    assert(enable_calls == 3 && prime_calls == 1);
    assert(device.DeviceConfig.Ep[1].In.dTDHead == td[1][1]);
    assert(device.DeviceConfig.Ep[1].In.dTDTail == td[1][1]);
    assert(device.DeviceConfig.Ep[1].Out.dTDCurr == td[1][0]);
    assert(device.DeviceConfig.Ep[2].In.dTDHead == td[2][1]);
    assert(device.DeviceConfig.Ep[2].In.dTDTail == td[2][1]);
    for (unsigned ep = 1; ep <= 2; ++ep) {
        unsigned dir = ep == 1 ? 1 : 1;
        for (unsigned i = 0; i < 3; ++i) {
            assert(td[ep][dir][i].token == TD_TERMINATE);
            assert(!(td[ep][dir][i].token & TD_ACTIVE));
        }
    }
    for (unsigned i = 0; i < 3; ++i) assert(td[1][0][i].token == TD_ACTIVE);
    assert(qh[1][1].next == 1U); /* helper leaves IN queue head terminated/empty */
    assert((ep1_bits & (XUSBPS_EPCR_TXR_MASK | XUSBPS_EPCR_RXR_MASK)) ==
           (XUSBPS_EPCR_TXR_MASK | XUSBPS_EPCR_RXR_MASK));
    assert(ep2_bits & XUSBPS_EPCR_TXR_MASK);
}

static void test_dtr_preserves_data_toggle(void) {
    setup_case(); seed_stale_queues();
    assert(eye_usb_rearm_data(&device, 0) == 0);
    assert(enable_calls == 3 && prime_calls == 1);
    assert(!(ep1_bits & (XUSBPS_EPCR_TXR_MASK | XUSBPS_EPCR_RXR_MASK)));
    assert(!(ep2_bits & XUSBPS_EPCR_TXR_MASK));
}

static void test_stuck_flush_never_reenables(void) {
    setup_case(); seed_stale_queues(); flush_stuck = 1;
    assert(eye_usb_rearm_data(&device, 1) == 1);
    assert(disable_calls == 3 && reconfigure_calls == 0);
    assert(enable_calls == 0 && prime_calls == 0);
}

static void test_stuck_prime_aborts_before_descriptor_mutation(void) {
    setup_case(); seed_stale_queues(); prime_stuck = 1;
    XUsbPs_dQH qh_before[3][2];
    XUsbPs_dTD td_before[3][2][4];
    memcpy(qh_before, qh, sizeof(qh));
    memcpy(td_before, td, sizeof(td));
    assert(eye_usb_rearm_data(&device, 1) == 1);
    assert(disable_calls == 3 && reconfigure_calls == 0);
    assert(enable_calls == 0 && prime_calls == 0);
    assert(completion_clear_calls == 0);
    assert(memcmp(qh_before, qh, sizeof(qh)) == 0);
    assert(memcmp(td_before, td, sizeof(td)) == 0);
}

static void test_reconfigure_failure_never_reenables(void) {
    setup_case(); seed_stale_queues(); reconfigure_fail_at = 2;
    assert(eye_usb_rearm_data(&device, 1) == 1);
    assert(disable_calls == 3 && reconfigure_calls == 2);
    assert(enable_calls == 0 && prime_calls == 0);
}

int main(void) {
    test_success_rebuilds_all_data_queues();
    test_dtr_preserves_data_toggle();
    test_stuck_flush_never_reenables();
    test_stuck_prime_aborts_before_descriptor_mutation();
    test_reconfigure_failure_never_reenables();
    puts("usb recovery helper fake-API tests: 5/5 PASS");
    return 0;
}
"""


class UsbRecoveryNativeTest(unittest.TestCase):
    def test_recovery_helper_state_flow(self):
        compiler = os.environ.get("CC") or shutil.which("gcc")
        if not compiler and os.name == "nt":
            candidate = Path("C:/msys64/ucrt64/bin/gcc.exe")
            if candidate.is_file():
                compiler = str(candidate)
        self.assertTrue(compiler, "A native GCC compiler is required for this helper test")

        with tempfile.TemporaryDirectory(prefix="eyepqc-usb-recovery-") as temp:
            temp_path = Path(temp)
            (temp_path / "xusbps.h").write_text(FAKE_XUSBPS_H, encoding="ascii")
            (temp_path / "xusbps_endpoint.h").write_text(FAKE_XUSBPS_ENDPOINT_H, encoding="ascii")
            source = temp_path / "test_usb_recovery.c"
            source.write_text(HARNESS_C, encoding="ascii")
            exe = temp_path / ("usb_recovery_test.exe" if os.name == "nt" else "usb_recovery_test")
            env = os.environ.copy()
            env["PATH"] = str(Path(compiler).resolve().parent) + os.pathsep + env.get("PATH", "")
            build = subprocess.run(
                [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                 "-I", str(temp_path), "-I", str(ROOT / "src/ps/include"), str(source), "-o", str(exe)],
                text=True,
                capture_output=True,
                cwd=ROOT,
                env=env,
            )
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            result = subprocess.run([str(exe)], check=True, text=True, capture_output=True, cwd=ROOT)
            self.assertIn("5/5 PASS", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
