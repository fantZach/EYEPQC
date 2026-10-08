/* Candidate G6 camera capture and bounded recovery; baseline g3_camera.c is included read-only. */
#include "g6_auto_recovery.h"

volatile struct g6_auto_recovery_diag g6_auto_recovery_diag __attribute__((aligned(64))) = {
    .magic = G6_AUTO_MAGIC
};

#define capture_frame g6_baseline_capture_frame
#define g3_usb_capture g3_usb_capture_legacy
#include "../src/g3_camera.c"
#undef capture_frame
#undef g3_usb_capture

#define CAMERA_AUTO_CFG ((1U << 25) | (1000U << 9) | (12U << 3) | 4U | 2U)
#define CAMERA_AUTO_DEADLINE_US 3000000U

static int wait_capture_deadline(void)
{
    XTime start;
    XTime_GetTime(&start);
    for (;;) {
        uint32_t sr = XAxiDma_ReadReg(CAP_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
        g6_auto_recovery_diag.status_register = sr;
        g6_auto_recovery_diag.busy_at_end =
            (uint32_t)XAxiDma_Busy(&capture, XAXIDMA_DEVICE_TO_DMA);
        if (sr & XAXIDMA_IRQ_ERROR_MASK) {
            g6_auto_recovery_diag.observation = G6_AUTO_CAPTURE_DMA_IRQ_ERROR;
            g6_auto_recovery_diag.elapsed_us = elapsed_us(start);
            return 1;
        }
        if (!g6_auto_recovery_diag.busy_at_end) {
            g6_auto_recovery_diag.elapsed_us = elapsed_us(start);
            return 0;
        }
        if (elapsed_us(start) >= CAMERA_AUTO_DEADLINE_US) {
            g6_auto_recovery_diag.observation = G6_AUTO_CAPTURE_BUSY_TIMEOUT;
            g6_auto_recovery_diag.elapsed_us = elapsed_us(start);
            return 2;
        }
    }
}

static int g6_auto_capture_frame(void)
{
    unsigned mode = g6_auto_recovery_request;
    g6_auto_recovery_request = G6_AUTO_TRIGGER_NONE;
    g6_auto_recovery_diag.observation = G6_AUTO_CAPTURE_NONE;
    g6_auto_recovery_diag.stage = 1;

    /* Trigger changes only the PL source/routing. The ordinary S2MM transfer below
       still starts and waits against its production 3-second deadline. */
    if (mode == G6_AUTO_TRIGGER_CAMERA_RESET) {
        g6_auto_recovery_diag.trigger_mode = mode;
        Xil_Out32(CAM_GPIO, CAMERA_AUTO_CFG | 0x80000000U);
        usleep(10000);
        g6_auto_recovery_diag.camera_status = Xil_In32(CAM_GPIO + 8);
    } else if (mode == G6_AUTO_TRIGGER_ROUTING_STALL) {
        g6_auto_recovery_diag.trigger_mode = mode;
        route(3, 0); /* axis_capture_route mode 3 disables every valid/ready path. */
    }

    memset(g3_frame, 0xa5, sizeof g3_frame);
    Xil_DCacheFlushRange((UINTPTR)g3_frame, sizeof g3_frame);
    if (XAxiDma_SimpleTransfer(&capture, (UINTPTR)g3_frame, FRAME_CAP,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS) {
        g6_auto_recovery_diag.observation = G6_AUTO_CAPTURE_TRANSFER_START_FAILED;
        return 14;
    }
    g6_auto_recovery_diag.busy_at_start =
        (uint32_t)XAxiDma_Busy(&capture, XAXIDMA_DEVICE_TO_DMA);
    g6_auto_recovery_diag.stage = 2;
    int wait_status = wait_capture_deadline();
    if (wait_status) return 14;

    Xil_DCacheInvalidateRange((UINTPTR)g3_frame, sizeof g3_frame);
    /* A memory-boundary violation takes precedence over any malformed length/JPEG. */
    for (unsigned i = FRAME_CAP; i < sizeof g3_frame; ++i) {
        if (g3_frame[i] != 0xa5) {
            g6_auto_recovery_diag.observation = G6_AUTO_CAPTURE_GUARD_BROKEN;
            return 16;
        }
    }
    g3_job.cap_status = XAxiDma_ReadReg(CAP_BASE,
        XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    unsigned n = XAxiDma_ReadReg(CAP_BASE,
        XAXIDMA_RX_OFFSET + XAXIDMA_BUFFLEN_OFFSET);
    if (n < 4 || n > FRAME_CAP || g3_frame[0] != 0xff || g3_frame[1] != 0xd8 ||
        g3_frame[n - 2] != 0xff || g3_frame[n - 1] != 0xd9) {
        g6_auto_recovery_diag.observation = G6_AUTO_CAPTURE_MALFORMED_JPEG;
        return 15;
    }
    g3_job.frame_length = n;
    g6_auto_recovery_diag.observation = G6_AUTO_CAPTURE_OK;
    g6_auto_recovery_diag.frame_length = n;
    g6_auto_recovery_diag.stage = 3;
    return 0;
}

int g3_usb_capture(const uint8_t **data, unsigned *size)
{
    int status = g6_auto_capture_frame();
    if (status) return status;
    route(2, 0);
    *data = g3_frame;
    *size = g3_job.frame_length;
    return 0;
}

int g6_candidate_recover_camera(void)
{
    g6_auto_recovery_diag.stage = 4;
    if (reset_dma()) return 1;
    route(1, 1);
    memset(g3_frame, 0, sizeof g3_frame);
    memset(g3_sealed, 0, sizeof g3_sealed);
    volatile uint8_t *key = g3_job.key;
    for (unsigned i = 0; i < sizeof g3_job.key; ++i) key[i] = 0;
    volatile uint8_t *nonce_prefix = g3_job.nonce_prefix;
    for (unsigned i = 0; i < sizeof g3_job.nonce_prefix; ++i) nonce_prefix[i] = 0;
    Xil_DCacheFlushRange((UINTPTR)g3_frame, sizeof g3_frame);
    Xil_DCacheFlushRange((UINTPTR)g3_sealed, sizeof g3_sealed);
    Xil_DCacheFlushRange((UINTPTR)&g3_job, sizeof g3_job);
    g3_usb_zeroize();
    int status = configure_camera(CAMERA_AUTO_CFG);
    g6_auto_recovery_diag.camera_status = Xil_In32(CAM_GPIO + 8);
    if (status) return status;
    route(1, 0);
    g6_auto_recovery_diag.recovery_count++;
    g6_auto_recovery_diag.stage = 5;
    return 0;
}
