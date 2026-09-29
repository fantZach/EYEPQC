/* Temporary CF7020B USB0 CDC ACM throughput probe; not production firmware. */
#include "xparameters.h"
#include "xusbps.h"
#include "xusbps_ch9.h"
#include "xusbps_hw.h"
#include "xinterrupt_wrap.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include <string.h>

#define CHUNK 16384
static XUsbPs usb;
static u8 dma_mem[65536] __attribute__((aligned(64)));
static u8 chunk[CHUNK] __attribute__((aligned(64)));
static u8 line_coding[8] __attribute__((aligned(64))) = {0x00, 0xc2, 0x01, 0x00, 0, 0, 8};
static volatile int configured, dtr, tx_ready = 1, line_pending;
static u32 block_no;

/* Device class CDC, ACM control interface 0 + data interface 1. Test VID/PID only. */
static const u8 dev_desc[] = {
    18,1,0,2, 2,2,1,64, 0xfd,0x03, 0x20,0x70, 0,1, 1,2,3,1
};
static const u8 cfg_desc[] = {
    9,2,75,0,2,1,0,0xc0,0,
    8,11,0,2,2,2,1,0,
    9,4,0,0,1,2,2,1,0,
    5,0x24,0,0x10,0x01,
    4,0x24,2,2,
    5,0x24,6,0,1,
    5,0x24,1,0,1,
    7,5,0x82,3,16,0,16,
    9,4,1,0,2,0x0a,0,0,0,
    7,5,0x01,2,0,2,0,
    7,5,0x81,2,0,2,0
};
_Static_assert(sizeof(cfg_desc) == 75, "CDC descriptor length");

u32 XUsbPs_Ch9SetupDevDescReply(u8 *buf, u32 cap) {
    if (cap < sizeof(dev_desc)) return 0;
    memcpy(buf, dev_desc, sizeof(dev_desc));
    return sizeof(dev_desc);
}
u32 XUsbPs_Ch9SetupCfgDescReply(u8 *buf, u32 cap) {
    if (cap < sizeof(cfg_desc)) return 0;
    memcpy(buf, cfg_desc, sizeof(cfg_desc));
    return sizeof(cfg_desc);
}
u32 XUsbPs_Ch9SetupStrDescReply(u8 *buf, u32 cap, u8 index) {
    static const char *const strings[] = {"", "EYEPQC", "USB Throughput Probe", "CF7020B-USB-PROBE"};
    if (index == 0) {
        if (cap < 4) return 0;
        buf[0] = 4; buf[1] = 3; buf[2] = 9; buf[3] = 4;
        return 4;
    }
    if (index >= sizeof(strings)/sizeof(strings[0])) return 0;
    u32 n = strlen(strings[index]);
    if (2*n+2 > cap) return 0;
    buf[0] = 2*n+2; buf[1] = 3;
    for (u32 i=0; i<n; ++i) { buf[2+2*i] = strings[index][i]; buf[3+2*i] = 0; }
    return 2*n+2;
}
void XUsbPs_SetConfiguration(XUsbPs *u, int index) {
    configured = index == 1;
    dtr = 0;
    tx_ready = 1;
    if (!configured) return;
    XUsbPs_EpEnable(u, 1, XUSBPS_EP_DIRECTION_OUT);
    XUsbPs_EpEnable(u, 1, XUSBPS_EP_DIRECTION_IN);
    XUsbPs_SetBits(u, XUSBPS_EPCR1_OFFSET, XUSBPS_EPCR_TXT_BULK_MASK |
                   XUSBPS_EPCR_RXT_BULK_MASK | XUSBPS_EPCR_TXR_MASK | XUSBPS_EPCR_RXR_MASK);
    XUsbPs_EpEnable(u, 2, XUSBPS_EP_DIRECTION_IN);
    XUsbPs_SetBits(u, XUSBPS_EPCR2_OFFSET, XUSBPS_EPCR_TXT_INTR_MASK | XUSBPS_EPCR_TXR_MASK);
}
void XUsbPs_SetConfigurationApp(XUsbPs *u, XUsbPs_SetupData *s) { (void)u; (void)s; }
void XUsbPs_SetInterfaceHandler(XUsbPs *u, XUsbPs_SetupData *s) { (void)u; (void)s; }

void XUsbPs_ClassReq(XUsbPs *u, XUsbPs_SetupData *s) {
    switch (s->bRequest) {
    case 0x20: /* SET_LINE_CODING */
        if (s->wLength != 7 || XUsbPs_EpPrime(u, 0, XUSBPS_EP_DIRECTION_OUT) != XST_SUCCESS) break;
        line_pending = 1;
        return;
    case 0x21: /* GET_LINE_CODING */
        XUsbPs_EpBufferSend(u, 0, line_coding, 7);
        return;
    case 0x22: /* SET_CONTROL_LINE_STATE */
        dtr = s->wValue & 1;
        if (dtr) block_no = 0;
        XUsbPs_EpBufferSend(u, 0, NULL, 0);
        return;
    case 0x23: /* SEND_BREAK */
        XUsbPs_EpBufferSend(u, 0, NULL, 0);
        return;
    default: break;
    }
    XUsbPs_EpStall(u, 0, XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
}

static void ep0(void *ref, u8 ep, u8 event, void *data) {
    (void)data;
    XUsbPs *u = ref;
    if (event == XUSBPS_EP_EVENT_SETUP_DATA_RECEIVED) {
        XUsbPs_SetupData setup;
        if (XUsbPs_EpGetSetupData(u, ep, &setup) == XST_SUCCESS)
            XUsbPs_Ch9HandleSetupPacket(u, &setup);
    } else if (event == XUSBPS_EP_EVENT_DATA_RX) {
        u8 *buf; u32 len, handle;
        if (XUsbPs_EpBufferReceive(u, ep, &buf, &len, &handle) == XST_SUCCESS) {
            if (line_pending) {
                if (len == 7) {
                    Xil_DCacheInvalidateRange((UINTPTR)buf, 32);
                    memcpy(line_coding, buf, 7);
                }
                line_pending = 0;
                XUsbPs_EpBufferSend(u, 0, NULL, 0);
            }
            XUsbPs_EpBufferRelease(handle);
        }
    }
}
static void ep1_in(void *ref, u8 ep, u8 event, void *data) {
    (void)ref; (void)ep; (void)data;
    if (event == XUSBPS_EP_EVENT_DATA_TX) tx_ready = 1;
}
static void usb_event(void *ref, u32 mask) { (void)ref; (void)mask; }

int main(void) {
    XUsbPs_Config *uc = XUsbPs_LookupConfig(XPAR_XUSBPS_0_BASEADDR);
    XUsbPs_DeviceConfig dc = {0};
    if (!uc || XUsbPs_CfgInitialize(&usb, uc, uc->BaseAddress) != XST_SUCCESS) goto fail;
    if (XSetupInterruptSystem(&usb, &XUsbPs_IntrHandler, uc->IntrId,
                              uc->IntrParent, XINTERRUPT_DEFAULT_PRIORITY) != XST_SUCCESS) goto fail;

    dc.NumEndpoints = 3;
    for (int i=0; i<3; ++i) {
        dc.EpCfg[i].Out.Type = i ? XUSBPS_EP_TYPE_BULK : XUSBPS_EP_TYPE_CONTROL;
        dc.EpCfg[i].Out.NumBufs = 2;
        dc.EpCfg[i].Out.BufSize = i == 1 ? 512 : 64;
        dc.EpCfg[i].Out.MaxPacketSize = i == 1 ? 512 : 64;
        dc.EpCfg[i].In.Type = i == 2 ? XUSBPS_EP_TYPE_INTERRUPT :
                              (i == 1 ? XUSBPS_EP_TYPE_BULK : XUSBPS_EP_TYPE_CONTROL);
        dc.EpCfg[i].In.NumBufs = 4;
        dc.EpCfg[i].In.MaxPacketSize = i == 1 ? 512 : (i == 2 ? 16 : 64);
    }
    memset(dma_mem, 0, sizeof(dma_mem));
    Xil_DCacheFlushRange((UINTPTR)dma_mem, sizeof(dma_mem));
    dc.DMAMemPhys = (u32)(UINTPTR)dma_mem;
    if (XUsbPs_ConfigureDevice(&usb, &dc) != XST_SUCCESS) goto fail;
    if (XUsbPs_IntrSetHandler(&usb, usb_event, NULL, XUSBPS_IXR_UE_MASK) != XST_SUCCESS ||
        XUsbPs_EpSetHandler(&usb, 0, XUSBPS_EP_DIRECTION_OUT, ep0, &usb) != XST_SUCCESS ||
        XUsbPs_EpSetHandler(&usb, 1, XUSBPS_EP_DIRECTION_IN, ep1_in, &usb) != XST_SUCCESS) goto fail;
    XUsbPs_IntrEnable(&usb, XUSBPS_IXR_UR_MASK | XUSBPS_IXR_UI_MASK);
    XUsbPs_Start(&usb);
    xil_printf("USB_PROBE_READY\r\n");
    for (;;) {
        if (!configured || !dtr || !tx_ready) continue;
        tx_ready = 0;
        memcpy(chunk, "EYEP", 4);
        chunk[4] = block_no; chunk[5] = block_no >> 8;
        chunk[6] = block_no >> 16; chunk[7] = block_no >> 24;
        for (u32 i=8; i<CHUNK; ++i) chunk[i] = (u8)(i + block_no);
        if (XUsbPs_EpBufferSend(&usb, 1, chunk, CHUNK) != XST_SUCCESS) {
            tx_ready = 1;
            continue;
        }
        ++block_no;
    }
fail:
    xil_printf("USB_PROBE_FAIL\r\n");
    for (;;) {}
}
