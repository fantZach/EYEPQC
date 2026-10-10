#ifndef EYE_USB_RECOVERY_H
#define EYE_USB_RECOVERY_H

#include "xusbps.h"
#include "xusbps_endpoint.h"
#include <string.h>

#ifndef EYE_USB_REARM_POLL_LIMIT
#define EYE_USB_REARM_POLL_LIMIT 4096U
#endif

/* Called only after the data endpoints have been disabled and flushed. The
 * SDK reconfiguration resets cursors/links but preserves old ACTIVE/error bits
 * and parts of the QH overlay, so clear the stopped DMA objects first. EP0 and
 * the controller stay running; this must not trigger another USB bus reset. */
static int eye_usb_rebuild_direction(XUsbPs *u, unsigned ep, unsigned dir) {
    XUsbPs_DeviceConfig *c = &u->DeviceConfig;
    XUsbPs_dQH *qh;
    XUsbPs_dTD *td;
    unsigned count;
    if (dir == XUSBPS_EP_DIRECTION_IN) {
        qh = c->Ep[ep].In.dQH;
        td = c->Ep[ep].In.dTDs;
        count = c->EpCfg[ep].In.NumBufs;
        c->Ep[ep].In.BufferPtr = NULL;
        c->Ep[ep].In.RequestedBytes = c->Ep[ep].In.BytesTxed = 0;
    } else {
        qh = c->Ep[ep].Out.dQH;
        td = c->Ep[ep].Out.dTDs;
        count = c->EpCfg[ep].Out.NumBufs;
        c->Ep[ep].Out.BufferPtr = NULL;
        c->Ep[ep].Out.MemAlloted = 0;
        c->Ep[ep].Out.RequestedBytes = c->Ep[ep].Out.BytesTxed = 0;
    }
    Xil_DCacheInvalidateRange((UINTPTR)td, count * sizeof(*td));
    Xil_DCacheInvalidateRange((UINTPTR)qh, sizeof(*qh));
    memset(td, 0, count * sizeof(*td));
    memset(qh, 0, sizeof(*qh));
    Xil_DCacheFlushRange((UINTPTR)td, count * sizeof(*td));
    Xil_DCacheFlushRange((UINTPTR)qh, sizeof(*qh));
    if (XUsbPs_ReconfigureEp(u, c, (int)ep, (unsigned short)dir, 0) != XST_SUCCESS)
        return 1;
    if (dir == XUSBPS_EP_DIRECTION_IN) {
        XUsbPs_WritedQH(qh, XUSBPS_dQHdTDNLP, 1U); /* empty/terminated */
        XUsbPs_dQHFlushCache(qh);
    }
    return 0;
}

static int eye_usb_rearm_data(XUsbPs *u, int reset_toggle) {
    const u32 mask = (1U << 1) | (1U << 17) | (1U << 18);
    XUsbPs_EpDisable(u, 1, XUSBPS_EP_DIRECTION_OUT);
    XUsbPs_EpDisable(u, 1, XUSBPS_EP_DIRECTION_IN);
    XUsbPs_EpDisable(u, 2, XUSBPS_EP_DIRECTION_IN);
    XUsbPs_WriteReg(u->Config.BaseAddress, XUSBPS_EPFLUSH_OFFSET, mask);
    unsigned remaining = EYE_USB_REARM_POLL_LIMIT;
    while ((XUsbPs_ReadReg(u->Config.BaseAddress, XUSBPS_EPFLUSH_OFFSET) & mask)
           && --remaining) {}
    if (!remaining) return 1;
    remaining = EYE_USB_REARM_POLL_LIMIT;
    while ((XUsbPs_ReadReg(u->Config.BaseAddress, XUSBPS_EPPRIME_OFFSET) & mask)
           && --remaining) {}
    if (!remaining) return 1;
    XUsbPs_WriteReg(u->Config.BaseAddress, XUSBPS_EPCOMPL_OFFSET, mask);
    if (eye_usb_rebuild_direction(u, 1, XUSBPS_EP_DIRECTION_OUT) ||
        eye_usb_rebuild_direction(u, 1, XUSBPS_EP_DIRECTION_IN) ||
        eye_usb_rebuild_direction(u, 2, XUSBPS_EP_DIRECTION_IN)) return 1;
    XUsbPs_EpEnable(u, 1, XUSBPS_EP_DIRECTION_OUT);
    XUsbPs_EpEnable(u, 1, XUSBPS_EP_DIRECTION_IN);
    /* SET_CONFIGURATION resets both peers' data toggles. DTR is only a CDC
     * control request: resetting our toggles there silently loses packets
     * because the host retains its endpoint sequence numbers. */
    XUsbPs_SetBits(u, XUSBPS_EPCR1_OFFSET, XUSBPS_EPCR_TXT_BULK_MASK |
                  XUSBPS_EPCR_RXT_BULK_MASK |
                  (reset_toggle ? XUSBPS_EPCR_TXR_MASK | XUSBPS_EPCR_RXR_MASK : 0));
    if (XUsbPs_EpPrime(u, 1, XUSBPS_EP_DIRECTION_OUT) != XST_SUCCESS) return 1;
    XUsbPs_EpEnable(u, 2, XUSBPS_EP_DIRECTION_IN);
    XUsbPs_SetBits(u, XUSBPS_EPCR2_OFFSET, XUSBPS_EPCR_TXT_INTR_MASK |
                  (reset_toggle ? XUSBPS_EPCR_TXR_MASK : 0));
    return 0;
}

#endif
