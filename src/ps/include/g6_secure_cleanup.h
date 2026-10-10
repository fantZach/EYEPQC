#ifndef EYEPQC_G6_SECURE_CLEANUP_H
#define EYEPQC_G6_SECURE_CLEANUP_H

#include <stddef.h>
#include <stdint.h>

#define G6_SECURE_CLEANUP_MAGIC 0x4736434cU

enum g6_secure_cleanup_stage {
    G6_CLEANUP_IDLE = 0,
    G6_CLEANUP_DMA_AND_GCM = 1,
    G6_CLEANUP_FRAME_AND_SEALED = 2,
    G6_CLEANUP_USB_TX_QUIESCE = 3,
    G6_CLEANUP_USB_TX_WIPE = 4,
    G6_CLEANUP_USB_TX_REBUILD = 5,
    G6_CLEANUP_COMPLETE = 6,
    G6_CLEANUP_FAILED = 0xffffffffU
};

/* JTAG-readable cleanup evidence. These fields contain addresses, lengths,
 * hardware status words and zero/nonzero readback only, never key/session data. */
struct g6_secure_cleanup_diag {
    uint32_t magic;
    volatile uint32_t stage;
    volatile uint32_t result;
    volatile uint32_t failed_stage;
    volatile uint32_t route_mode;
    volatile uint32_t dma_reset_status;
    volatile uint32_t capture_rx_status;
    volatile uint32_t crypto_rx_status;
    volatile uint32_t crypto_tx_status;
    volatile uint32_t gcm_status;
    volatile uint32_t frame_address;
    volatile uint32_t frame_capacity;
    volatile uint32_t frame_zero_or;
    volatile uint32_t sealed_address;
    volatile uint32_t sealed_capacity;
    volatile uint32_t sealed_zero_or;
    volatile uint32_t usb_quiesce_status;
    volatile uint32_t usb_flush_status;
    volatile uint32_t usb_prime_status;
    volatile uint32_t usb_completion_status;
    volatile uint32_t usb_poll_limit;
    volatile uint32_t usb_flush_polls;
    volatile uint32_t usb_prime_polls;
    volatile uint32_t usb_rebuild_status;
    volatile uint32_t tx_address;
    volatile uint32_t tx_capacity;
    volatile uint32_t tx_zero_or;
};

_Static_assert(sizeof(struct g6_secure_cleanup_diag) == 108U,
               "G6 cleanup diagnostic ABI size changed");
_Static_assert(offsetof(struct g6_secure_cleanup_diag, frame_address) == 40U &&
               offsetof(struct g6_secure_cleanup_diag, sealed_address) == 52U &&
               offsetof(struct g6_secure_cleanup_diag, usb_completion_status) == 76U &&
               offsetof(struct g6_secure_cleanup_diag, tx_address) == 96U &&
               offsetof(struct g6_secure_cleanup_diag, tx_capacity) == 100U &&
               offsetof(struct g6_secure_cleanup_diag, tx_zero_or) == 104U,
               "G6 cleanup diagnostic field offsets changed");

extern volatile struct g6_secure_cleanup_diag g6_secure_cleanup_diag;

struct g6_secure_cleanup_ops {
    int (*stop_dma_and_clear_gcm)(void *context);
    int (*wipe_frame_and_sealed)(void *context);
    int (*quiesce_wipe_rebuild_usb_tx)(void *context);
};

struct g6_secure_usb_tx_ops {
    int (*quiesce)(void *context);
    int (*wipe_and_verify)(void *context);
    int (*rebuild)(void *context);
};

/* Shared orchestration makes the production cleanup order testable offline.
 * Each callback returns success only after its object ownership proof and any
 * required full-capacity readback have succeeded. */
static inline int g6_secure_cleanup_run(
    void *context, const struct g6_secure_cleanup_ops *ops,
    volatile struct g6_secure_cleanup_diag *diag)
{
    int status;
    if (!ops || !diag || !ops->stop_dma_and_clear_gcm ||
        !ops->wipe_frame_and_sealed || !ops->quiesce_wipe_rebuild_usb_tx)
        return 1;

    diag->result = 1U;
    diag->failed_stage = G6_CLEANUP_IDLE;
    diag->stage = G6_CLEANUP_DMA_AND_GCM;
    status = ops->stop_dma_and_clear_gcm(context);
    if (status) goto failed;

    diag->stage = G6_CLEANUP_FRAME_AND_SEALED;
    status = ops->wipe_frame_and_sealed(context);
    if (status) goto failed;

    diag->stage = G6_CLEANUP_USB_TX_QUIESCE;
    status = ops->quiesce_wipe_rebuild_usb_tx(context);
    if (status) goto failed;

    diag->stage = G6_CLEANUP_COMPLETE;
    diag->result = 0U;
    return 0;

failed:
    diag->result = (uint32_t)status;
    diag->failed_stage = diag->stage;
    diag->stage = G6_CLEANUP_FAILED;
    return status ? status : 1;
}

/* The USB wrapper holds IRQs masked across this sequence so DATA_TX or USB
 * event handlers cannot change endpoint ownership while the ring is rebuilt. */
static inline int g6_secure_usb_tx_cleanup_run(
    void *context, const struct g6_secure_usb_tx_ops *ops,
    volatile struct g6_secure_cleanup_diag *diag)
{
    int status;
    if (!ops || !diag || !ops->quiesce || !ops->wipe_and_verify || !ops->rebuild)
        return 1;
    diag->stage = G6_CLEANUP_USB_TX_QUIESCE;
    status = ops->quiesce(context);
    if (status) return status;
    diag->stage = G6_CLEANUP_USB_TX_WIPE;
    status = ops->wipe_and_verify(context);
    if (status) return status;
    diag->stage = G6_CLEANUP_USB_TX_REBUILD;
    return ops->rebuild(context);
}

/* Volatile stores prevent the compiler from eliding the actual wipe. */
static inline void g6_secure_wipe_bytes(void *memory, size_t length)
{
    volatile uint8_t *bytes = (volatile uint8_t *)memory;
    for (size_t i = 0; i < length; ++i) bytes[i] = 0;
}

static inline uint32_t g6_secure_zero_or(const void *memory, size_t length)
{
    const volatile uint8_t *bytes = (const volatile uint8_t *)memory;
    uint32_t value = 0;
    for (size_t i = 0; i < length; ++i) value |= bytes[i];
    return value;
}

static inline int g6_secure_dma_channel_stopped(uint32_t status,
                                                uint32_t error_mask,
                                                uint32_t halted_mask,
                                                uint32_t idle_mask)
{
    return !(status & error_mask) && (status & (halted_mask | idle_mask)) != 0U;
}

static inline int g6_secure_gcm_status_cleared(uint32_t status)
{
    return (status & 7U) == 0U;
}

static inline int g6_secure_usb_tx_unowned(int flush_succeeded,
                                            uint32_t flush_status,
                                            uint32_t prime_status)
{
    return flush_succeeded && flush_status == 0U && prime_status == 0U;
}

/* send_frame() maps usb_cdc_send failures to status 4. A normal host close is
 * only classified as disconnect after readiness drops or the connection epoch
 * changes; an in-place send failure remains a transport fault. */
static inline int g6_secure_expected_usb_disconnect(unsigned send_status,
                                                     unsigned resume_status,
                                                     unsigned usb_ready,
                                                     uint32_t epoch_before,
                                                     uint32_t epoch_after)
{
    return !resume_status && send_status == 4U &&
           (!usb_ready || epoch_before != epoch_after);
}

#endif
