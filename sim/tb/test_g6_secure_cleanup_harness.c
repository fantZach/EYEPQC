#include "g6_secure_cleanup.h"

#include <stdio.h>
#include <string.h>

#define CAPACITY_FRAME (65536U + 64U)
#define CAPACITY_SEALED 68096U
#define CAPACITY_TX 1472U
/* Values verified from the candidate007 pinned xaxidma_hw.h: ERR_ALL_MASK
 * is 0x770 and IRQ_ERROR_MASK is 0x4000. The production code uses those BSP
 * macros directly; these values exercise the same mask in this SDK-free test. */
#define DMA_ERR_ALL 0x00000770U
#define DMA_IRQ_ERROR 0x00004000U
#define DMA_ERROR_MASK (DMA_ERR_ALL | DMA_IRQ_ERROR)
#define DMA_HALTED 0x00000001U
#define DMA_IDLE 0x00000002U

struct fake_hardware {
    unsigned reset_done;
    uint32_t dma_status[3];
    uint32_t gcm_status;
    unsigned usb_flush_ok;
    uint32_t usb_flush_status;
    uint32_t usb_prime_status;
    int fail_frame_wipe;
    int fail_tx_rebuild;
    unsigned calls[8];
    unsigned count;
};

static int fake_prepare(void *opaque)
{
    struct fake_hardware *hw = opaque;
    hw->calls[hw->count++] = 1U;
    if (!hw->reset_done) return 11;
    for (unsigned i = 0; i < 3; ++i)
        if (!g6_secure_dma_channel_stopped(hw->dma_status[i], DMA_ERROR_MASK,
                                            DMA_HALTED, DMA_IDLE)) return 12;
    return g6_secure_gcm_status_cleared(hw->gcm_status) ? 0 : 13;
}

static int fake_frame_wipe(void *opaque)
{
    struct fake_hardware *hw = opaque;
    hw->calls[hw->count++] = 2U;
    return hw->fail_frame_wipe ? 14 : 0;
}

struct usb_fixture {
    struct fake_hardware *hw;
    unsigned wiped;
    unsigned rebuilt;
    unsigned sequence;
};

static int usb_quiesce(void *opaque)
{
    struct usb_fixture *fixture = opaque;
    fixture->sequence = fixture->sequence * 10U + 1U;
    return g6_secure_usb_tx_unowned((int)fixture->hw->usb_flush_ok,
                                     fixture->hw->usb_flush_status,
                                     fixture->hw->usb_prime_status) ? 0 : 21;
}

static int usb_wipe(void *opaque)
{
    struct usb_fixture *fixture = opaque;
    fixture->sequence = fixture->sequence * 10U + 2U;
    fixture->wiped++;
    return 0;
}

static int usb_rebuild(void *opaque)
{
    struct usb_fixture *fixture = opaque;
    fixture->sequence = fixture->sequence * 10U + 3U;
    fixture->rebuilt++;
    return fixture->hw->fail_tx_rebuild ? 22 : 0;
}

static int run_usb_cleanup(struct fake_hardware *hw, struct g6_secure_cleanup_diag *diag,
                           struct usb_fixture *fixture)
{
    const struct g6_secure_usb_tx_ops ops = {usb_quiesce, usb_wipe, usb_rebuild};
    fixture->hw = hw;
    return g6_secure_usb_tx_cleanup_run(fixture, &ops, diag);
}

static int fake_usb_callback(void *opaque)
{
    struct fake_hardware *hw = opaque;
    hw->calls[hw->count++] = 3U;
    struct g6_secure_cleanup_diag diag = {0};
    struct usb_fixture fixture = {0};
    return run_usb_cleanup(hw, &diag, &fixture);
}

static const struct g6_secure_cleanup_ops cleanup_ops = {
    fake_prepare, fake_frame_wipe, fake_usb_callback
};

static int test_full_capacity_wipe(void)
{
    struct guarded_frame { uint8_t pre[64]; uint8_t bytes[CAPACITY_FRAME]; uint8_t post[64]; };
    struct guarded_sealed { uint8_t pre[64]; uint8_t bytes[CAPACITY_SEALED]; uint8_t post[64]; };
    struct guarded_tx { uint8_t pre[64]; uint8_t bytes[CAPACITY_TX]; uint8_t post[64]; };
    static struct guarded_frame frame;
    static struct guarded_sealed sealed;
    static struct guarded_tx tx;
    memset(&frame, 0x5a, sizeof frame);
    memset(&sealed, 0x5a, sizeof sealed);
    memset(&tx, 0x5a, sizeof tx);
    g6_secure_wipe_bytes(frame.bytes, sizeof frame.bytes);
    g6_secure_wipe_bytes(sealed.bytes, sizeof sealed.bytes);
    g6_secure_wipe_bytes(tx.bytes, sizeof tx.bytes);
    if (g6_secure_zero_or(frame.bytes, sizeof frame.bytes) ||
        g6_secure_zero_or(sealed.bytes, sizeof sealed.bytes) ||
        g6_secure_zero_or(tx.bytes, sizeof tx.bytes)) return 1;
    for (unsigned i = 0; i < 64; ++i)
        if (frame.pre[i] != 0x5a || frame.post[i] != 0x5a ||
            sealed.pre[i] != 0x5a || sealed.post[i] != 0x5a ||
            tx.pre[i] != 0x5a || tx.post[i] != 0x5a) return 2;
    return 0;
}

static int test_gates_and_order(void)
{
    struct fake_hardware hw = {0};
    struct g6_secure_cleanup_diag diag = {.magic = G6_SECURE_CLEANUP_MAGIC};
    hw.reset_done = 1;
    hw.dma_status[0] = hw.dma_status[1] = hw.dma_status[2] = DMA_HALTED;
    hw.gcm_status = 0;
    hw.usb_flush_ok = 1;
    const unsigned bad_statuses[] = {0U, DMA_HALTED | DMA_IRQ_ERROR};
    for (unsigned i = 0; i < sizeof bad_statuses / sizeof bad_statuses[0]; ++i) {
        struct fake_hardware failed = hw;
        failed.dma_status[1] = bad_statuses[i];
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) ||
            failed.count != 1U || diag.failed_stage != G6_CLEANUP_DMA_AND_GCM)
            return 10 + (int)i;
    }
    for (unsigned channel = 0; channel < 3; ++channel) {
        struct fake_hardware failed = hw;
        failed.dma_status[channel] = DMA_ERROR_MASK | DMA_IDLE;
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) || failed.count != 1U)
            return 12 + (int)channel;
    }
    {
        const uint32_t error_bits[] = {0x00000010U, 0x00000020U,
            0x00000040U, 0x00000100U, 0x00000200U, 0x00000400U,
            DMA_IRQ_ERROR};
        for (unsigned channel = 0; channel < 3; ++channel) {
            for (unsigned bit = 0; bit < sizeof error_bits / sizeof error_bits[0]; ++bit) {
                struct fake_hardware failed = hw;
                failed.dma_status[channel] = DMA_HALTED | error_bits[bit];
                if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) || failed.count != 1U)
                    return 30 + (int)(channel * 8U + bit);
            }
        }
    }
    for (uint32_t status = 1U; status <= 4U; status <<= 1) {
        struct fake_hardware failed = hw;
        failed.gcm_status = status;
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) || failed.count != 1U)
            return 15 + (int)status;
    }
    {
        struct fake_hardware failed = hw;
        failed.reset_done = 0;
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) || failed.count != 1U)
            return 20;
    }
    {
        struct fake_hardware failed = hw;
        failed.usb_flush_ok = 0;
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) ||
            failed.count != 3U || diag.failed_stage != G6_CLEANUP_USB_TX_QUIESCE)
            return 21;
    }
    {
        struct fake_hardware failed = hw;
        failed.usb_prime_status = 1U << 17;
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) || failed.count != 3U)
            return 22;
    }
    {
        struct fake_hardware failed = hw;
        failed.usb_flush_status = 1U << 17;
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) || failed.count != 3U)
            return 23;
    }
    {
        struct fake_hardware failed = hw;
        failed.fail_frame_wipe = 1;
        if (!g6_secure_cleanup_run(&failed, &cleanup_ops, &diag) ||
            failed.count != 2U || diag.failed_stage != G6_CLEANUP_FRAME_AND_SEALED)
            return 24;
    }
    hw.count = 0;
    if (g6_secure_cleanup_run(&hw, &cleanup_ops, &diag) || hw.count != 3U ||
        hw.calls[0] != 1U || hw.calls[1] != 2U || hw.calls[2] != 3U ||
        diag.stage != G6_CLEANUP_COMPLETE || diag.result != 0U)
        return 25;
    return 0;
}

static int test_tx_sequence_and_disconnect_classification(void)
{
    struct fake_hardware hw = {0};
    struct g6_secure_cleanup_diag diag = {0};
    struct usb_fixture fixture = {0};
    hw.usb_flush_ok = 1;
    if (run_usb_cleanup(&hw, &diag, &fixture) || fixture.sequence != 123U ||
        fixture.wiped != 1U || fixture.rebuilt != 1U) return 1;
    fixture = (struct usb_fixture){0};
    hw.usb_prime_status = 1U;
    if (!run_usb_cleanup(&hw, &diag, &fixture) || fixture.sequence != 1U ||
        fixture.wiped || fixture.rebuilt) return 2;
    fixture = (struct usb_fixture){0};
    hw.usb_prime_status = 0U;
    hw.fail_tx_rebuild = 1;
    if (!run_usb_cleanup(&hw, &diag, &fixture) || fixture.sequence != 123U ||
        fixture.wiped != 1U || fixture.rebuilt != 1U) return 3;
    if (!g6_secure_expected_usb_disconnect(4U, 0U, 0U, 7U, 7U) ||
        !g6_secure_expected_usb_disconnect(4U, 0U, 1U, 7U, 8U) ||
        g6_secure_expected_usb_disconnect(4U, 0U, 1U, 7U, 7U) ||
        g6_secure_expected_usb_disconnect(3U, 0U, 0U, 7U, 8U) ||
        g6_secure_expected_usb_disconnect(4U, 1U, 0U, 7U, 8U)) return 4;
    return 0;
}

int main(void)
{
    int a = test_full_capacity_wipe();
    int b = test_gates_and_order();
    int c = test_tx_sequence_and_disconnect_classification();
    if (a || b || c) {
        fprintf(stderr, "secure_cleanup_failed=%d,%d,%d\n", a, b, c);
        return 1;
    }
    puts("full_capacity_wipe=PASS gates_and_order=PASS tx_sequence=PASS disconnect_classification=PASS");
    return 0;
}
