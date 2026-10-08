/* Isolated G6 camera-reset/DMA-stall experiment, built only by its variant script. */
#include "../src/g3_camera.c"
#include "g6_camera_fault_diag.h"

#define CAMERA_DIAG_CFG ((1U << 25) | (1000U << 9) | (12U << 3) | 4U | 2U)
#define CAPTURE_TIMEOUT_US 5000U

static uint32_t diag_hash(const uint8_t *data, unsigned size)
{
    uint32_t value = 2166136261U;
    for (unsigned i = 0; i < size; ++i) value = (value ^ data[i]) * 16777619U;
    return value;
}

int g3_usb_camera_reset_dma_stall(volatile struct g6_camera_fault_diag *diag)
{
    XTime start;
    unsigned elapsed;
    uint32_t status;
    if (!diag || diag->magic != G6_CAMERA_DIAG_MAGIC) return 1;

    diag->stage = 0;
    diag->result = 0;
    if (reset_dma()) return 2;
    route(1, 1);
    diag->stage = 1;

    /* This is an intentional PL-controlled OV5640 reset/PWDN, not a sensor unplug. */
    Xil_Out32(CAM_GPIO, CAMERA_DIAG_CFG | 0x80000000U);
    usleep(10000);
    diag->camera_stopped_status = Xil_In32(CAM_GPIO + 8);
    if ((diag->camera_stopped_status & ((1U << 23) | (1U << 19) | (1U << 20) | (1U << 16)))
        != (1U << 20)) return 3;
    route(1, 0);
    diag->stage = 2;

    memset(g3_frame, 0xa5, sizeof g3_frame);
    if (XAxiDma_SimpleTransfer(&capture, (UINTPTR)g3_frame, FRAME_CAP,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS) return 4;
    diag->capture_sr_armed = XAxiDma_ReadReg(CAP_BASE,
        XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    diag->capture_busy_armed = (uint32_t)XAxiDma_Busy(&capture, XAXIDMA_DEVICE_TO_DMA);
    diag->stage = 3;
    if (!diag->capture_busy_armed ||
        (diag->capture_sr_armed & XAXIDMA_IRQ_ERROR_MASK)) return 5;

    XTime_GetTime(&start);
    while (XAxiDma_Busy(&capture, XAXIDMA_DEVICE_TO_DMA)) {
        status = XAxiDma_ReadReg(CAP_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
        if (status & XAXIDMA_IRQ_ERROR_MASK) return 6;
        elapsed = elapsed_us(start);
        if (elapsed >= CAPTURE_TIMEOUT_US) break;
    }
    diag->timeout_us = elapsed_us(start);
    diag->capture_sr_timeout = XAxiDma_ReadReg(CAP_BASE,
        XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    diag->capture_busy_timeout = (uint32_t)XAxiDma_Busy(&capture, XAXIDMA_DEVICE_TO_DMA);
    diag->stage = 4;
    if (diag->timeout_us < CAPTURE_TIMEOUT_US || !diag->capture_busy_timeout ||
        (diag->capture_sr_timeout & XAXIDMA_IRQ_ERROR_MASK)) return 7;

    if (reset_dma()) return 8;
    diag->reset_status = XAxiDma_ReadReg(CAP_BASE,
        XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    diag->stage = 5;

    status = (uint32_t)configure_camera(CAMERA_DIAG_CFG);
    diag->camera_recovered_status = Xil_In32(CAM_GPIO + 8);
    diag->stage = 6;
    if (status) return 10 + (int)status;

    status = (uint32_t)capture_frame();
    if (status) return 40 + (int)status;
    diag->recovered_frame_length = g3_job.frame_length;
    diag->recovered_frame_hash = diag_hash(g3_frame, g3_job.frame_length);
    diag->stage = 7;
    g3_usb_zeroize();
    return 0;
}
