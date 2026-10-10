#ifndef EYE_USB_RECOVERY_H
#define EYE_USB_RECOVERY_H

#include "xusbps.h"
#include "xusbps_endpoint.h"
#include <string.h>

#ifndef EYE_USB_REARM_POLL_LIMIT
#define EYE_USB_REARM_POLL_LIMIT 4096U
#endif

/* EP1/EP2 data queues are writable only after endpoint disable reads back,
 * FLUSH and PRIME clear, and ENDPTSTAT (EPRDY) reports inactive. If a packet
 * was in flight when FLUSH completed, issue another bounded FLUSH. Each poll
 * class has a total budget, including retries. */
static int eye_usb_quiesce_data_endpoint(XUsbPs *u, unsigned ep, unsigned dir,
                                         u32 mask) {
    u32 disabled_mask = 0U;
    u32 flush_polls = 0U, prime_polls = 0U, active_polls = 0U;
    u32 active_status = 0U;
    if (u == NULL || ep == 0U || mask == 0U) return 1;
    if (dir & XUSBPS_EP_DIRECTION_OUT) disabled_mask |= XUSBPS_EPCR_RXE_MASK;
    if (dir & XUSBPS_EP_DIRECTION_IN) disabled_mask |= XUSBPS_EPCR_TXE_MASK;
    if (disabled_mask == 0U) return 1;

    XUsbPs_EpDisable(u, ep, dir);
#if defined(__arm__) && !defined(G6_USB_NATIVE_TEST)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
    if ((XUsbPs_ReadReg(u->Config.BaseAddress, XUSBPS_EPCRn_OFFSET(ep)) &
         disabled_mask) != 0U) return 1;

    while (flush_polls < EYE_USB_REARM_POLL_LIMIT &&
           prime_polls < EYE_USB_REARM_POLL_LIMIT &&
           active_polls < EYE_USB_REARM_POLL_LIMIT) {
        int flush_done = 0, prime_clear = 0;
        XUsbPs_WriteReg(u->Config.BaseAddress, XUSBPS_EPFLUSH_OFFSET, mask);
        while (flush_polls < EYE_USB_REARM_POLL_LIMIT) {
            ++flush_polls;
            if ((XUsbPs_ReadReg(u->Config.BaseAddress, XUSBPS_EPFLUSH_OFFSET) &
                 mask) == 0U) {
                flush_done = 1;
                break;
            }
        }
        if (!flush_done) break;
        while (prime_polls < EYE_USB_REARM_POLL_LIMIT) {
            ++prime_polls;
            if ((XUsbPs_ReadReg(u->Config.BaseAddress, XUSBPS_EPPRIME_OFFSET) &
                 mask) == 0U) {
                prime_clear = 1;
                break;
            }
        }
        if (!prime_clear) break;
        active_status = XUsbPs_ReadReg(u->Config.BaseAddress,
                                       XUSBPS_EPRDY_OFFSET) & mask;
        ++active_polls;
        if (active_status == 0U) return 0;
    }
    return 1;
}

/* Called only after the data endpoints have read back disabled and passed
 * FLUSH, PRIME, and inactive ENDPTSTAT. The
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
    if (u == NULL ||
        eye_usb_quiesce_data_endpoint(u, 1U, XUSBPS_EP_DIRECTION_OUT, 1U << 1) ||
        eye_usb_quiesce_data_endpoint(u, 1U, XUSBPS_EP_DIRECTION_IN, 1U << 17) ||
        eye_usb_quiesce_data_endpoint(u, 2U, XUSBPS_EP_DIRECTION_IN, 1U << 18))
        return 1;
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
