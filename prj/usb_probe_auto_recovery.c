/* Candidate-only USB probe wrapper to clear buffered pre-recovery control messages. */
#include "usb_probe.c"
#include "g6_secure_cleanup.h"
#include "g6_rekey_diag.h"
#include "usb_bounded_sdk_policy.h"

#define G6_USB_TX_QUIESCE_POLL_LIMIT 256U

void usb_cdc_g6_diag_fill(volatile struct g6_rekey_diag *diag)
{
    const uint32_t ep1_in_mask = 1U << 17U;
    if (!diag) return;
    diag->usb_configured = configured ? 1U : 0U;
    diag->usb_dtr = dtr ? 1U : 0U;
    diag->connection_epoch = connection_epoch;
    diag->tx_ready = tx_ready ? 1U : 0U;
#ifdef G6_USB
    diag->rx_head = rx_head;
    diag->rx_tail = rx_tail;
    diag->rx_bad = rx_bad ? 1U : 0U;
    diag->rx_bytes_buffered = (rx_head - rx_tail) & 2047U;
    diag->ep1_prime = XUsbPs_ReadReg(usb.Config.BaseAddress,
                                     XUSBPS_EPPRIME_OFFSET) & ep1_in_mask;
    diag->ep1_ready = XUsbPs_ReadReg(usb.Config.BaseAddress,
                                     XUSBPS_EPRDY_OFFSET) & ep1_in_mask;
    diag->epcr1 = XUsbPs_ReadReg(usb.Config.BaseAddress, XUSBPS_EPCR1_OFFSET);
    diag->ep1_completion = XUsbPs_ReadReg(usb.Config.BaseAddress,
                                          XUSBPS_EPCOMPL_OFFSET) & ep1_in_mask;
    diag->ep1_flush = XUsbPs_ReadReg(usb.Config.BaseAddress,
                                     XUSBPS_EPFLUSH_OFFSET) & ep1_in_mask;
#else
    diag->rx_head = diag->rx_tail = diag->rx_bad = diag->rx_bytes_buffered = 0U;
    diag->ep1_prime = diag->ep1_ready = diag->epcr1 = 0U;
    diag->ep1_completion = diag->ep1_flush = 0U;
#endif
}

static uint32_t usb_irq_save_disable(void)
{
#if defined(__arm__)
    uint32_t saved;
    __asm__ volatile("mrs %0, cpsr\n\tcpsid i" : "=r"(saved) :: "memory", "cc");
    return saved;
#else
    return 0;
#endif
}

static void usb_irq_restore(uint32_t saved)
{
#if defined(__arm__)
    if (saved & 0x80U) __asm__ volatile("cpsid i" ::: "memory", "cc");
    else __asm__ volatile("cpsie i" ::: "memory", "cc");
#else
    (void)saved;
#endif
}

struct secure_tx_context {
    XUsbPs *usb;
    uint8_t *buffer;
    unsigned capacity;
};

static int secure_tx_quiesce(void *context)
{
    struct secure_tx_context *tx_context = context;
    XUsbPs *u = tx_context->usb;
    volatile struct g6_secure_cleanup_diag *diag = &g6_secure_cleanup_diag;
    const u32 in_mask = 1U << (1U + XUSBPS_EPFLUSH_TX_SHIFT);
    u32 flush_polls = 0U, prime_polls = 0U;
    diag->usb_poll_limit = G6_USB_TX_QUIESCE_POLL_LIMIT;
    int status = XUsbPs_BoundedQuiesceInEndpointWithLimit(
        u, 1U, in_mask, in_mask, G6_USB_TX_QUIESCE_POLL_LIMIT,
        &flush_polls, &prime_polls);
    diag->usb_flush_polls = flush_polls;
    diag->usb_prime_polls = prime_polls;
    diag->usb_flush_status = XUsbPs_ReadReg(u->Config.BaseAddress,
                                             XUSBPS_EPFLUSH_OFFSET) & in_mask;
    diag->usb_prime_status = XUsbPs_ReadReg(u->Config.BaseAddress,
                                             XUSBPS_EPPRIME_OFFSET) & in_mask;
    diag->usb_quiesce_status = (uint32_t)status;
    return g6_secure_usb_tx_unowned(status == XST_SUCCESS,
                                    diag->usb_flush_status,
                                    diag->usb_prime_status) ? 0 : 1;
}

static int secure_tx_wipe(void *context)
{
    struct secure_tx_context *tx_context = context;
    volatile struct g6_secure_cleanup_diag *diag = &g6_secure_cleanup_diag;
    uint32_t zero_or;
    diag->tx_address = (uint32_t)(UINTPTR)tx_context->buffer;
    diag->tx_capacity = tx_context->capacity;
    Xil_DCacheInvalidateRange((UINTPTR)tx_context->buffer, tx_context->capacity);
    g6_secure_wipe_bytes(tx_context->buffer, tx_context->capacity);
    Xil_DCacheFlushRange((UINTPTR)tx_context->buffer, tx_context->capacity);
    __asm__ volatile("dsb sy" ::: "memory");
    Xil_DCacheInvalidateRange((UINTPTR)tx_context->buffer, tx_context->capacity);
    zero_or = g6_secure_zero_or(tx_context->buffer, tx_context->capacity);
    diag->tx_zero_or = zero_or;
    return zero_or == 0U ? 0 : 1;
}

static int secure_tx_rebuild(void *context)
{
    struct secure_tx_context *tx_context = context;
    XUsbPs *u = tx_context->usb;
    volatile struct g6_secure_cleanup_diag *diag = &g6_secure_cleanup_diag;
    const u32 in_completion_mask = 1U << 17U;
    int completion_status = XUsbPs_BoundedClearEndpointCompletion(
        u, in_completion_mask);
    diag->usb_completion_status = XUsbPs_ReadReg(u->Config.BaseAddress,
        XUSBPS_EPCOMPL_OFFSET) & in_completion_mask;
    if (completion_status != XST_SUCCESS || diag->usb_completion_status != 0U)
        return 1;
    int status = eye_usb_rebuild_direction(u, 1U, XUSBPS_EP_DIRECTION_IN);
    diag->usb_rebuild_status = (uint32_t)status;
    if (status) return 1;
    XUsbPs_BoundedClearEndpointFault(u, 1U);
    if (configured && dtr) XUsbPs_EpEnable(u, 1U, XUSBPS_EP_DIRECTION_IN);
    tx_ready = 1;
    return 0;
}

static int secure_tx_cleanup(XUsbPs *usb, uint8_t *buffer, unsigned capacity)
{
    static const struct g6_secure_usb_tx_ops ops = {
        secure_tx_quiesce, secure_tx_wipe, secure_tx_rebuild
    };
    struct secure_tx_context context = {usb, buffer, capacity};
    uint32_t irq_state = usb_irq_save_disable();
    int status = g6_secure_usb_tx_cleanup_run(&context, &ops,
                                               &g6_secure_cleanup_diag);
    usb_irq_restore(irq_state);
    return status;
}

int usb_cdc_secure_cleanup_tx(uint8_t *buffer, unsigned capacity)
{
#ifdef G6_USB
    if (!buffer || !capacity || (((UINTPTR)buffer | capacity) & 63U)) return 1;
    return secure_tx_cleanup(&usb, buffer, capacity);
#else
    (void)buffer;
    (void)capacity;
    return 1;
#endif
}

int usb_cdc_clear_control_queue(void)
{
#ifdef G6_USB
    if (!configured || !dtr || eye_usb_rearm_data(&usb, 0)) {
        ++usb_recovery_failures;
        configured = 0;
        tx_ready = 1;
        rx_reset();
        return 1;
    }
    rx_reset();
    memset(rx_ring, 0, sizeof rx_ring);
    memset(control_record, 0, sizeof control_record);
    Xil_DCacheFlushRange((UINTPTR)rx_ring, sizeof rx_ring);
    Xil_DCacheFlushRange((UINTPTR)control_record, sizeof control_record);
    tx_ready = 1;
    return 0;
#else
    return 1;
#endif
}
