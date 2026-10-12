/* G6 diagnostic wrapper; the baseline G6 USB source remains byte-identical. */
#include "g6_camera_fault_diag.h"

volatile uint32_t g6_camera_fault_inject __attribute__((aligned(64)));
volatile struct g6_camera_fault_diag g6_camera_fault_diag __attribute__((aligned(64)));

int g6_camera_fault_capture(const uint8_t **data, unsigned *size);

#define g3_usb_capture g6_camera_fault_capture
#include "../src/g6_usb.c"
#undef g3_usb_capture

int g3_usb_capture(const uint8_t **data, unsigned *size);
int g3_usb_camera_reset_dma_stall(volatile struct g6_camera_fault_diag *diag);

int g6_camera_fault_capture(const uint8_t **data, unsigned *size)
{
    int status;
    if (g6_camera_fault_inject != 1U) return g3_usb_capture(data, size);

    g6_camera_fault_inject = 0;
    g6_camera_fault_diag.magic = G6_CAMERA_DIAG_MAGIC;
    g6_camera_fault_diag.state = G6_CAMERA_DIAG_RUNNING;
    g6_camera_fault_diag.stage = 0;
    status = g3_usb_camera_reset_dma_stall(&g6_camera_fault_diag);
    g6_camera_fault_diag.result = (uint32_t)status;
    if (status) {
        g6_camera_fault_diag.state = G6_CAMERA_DIAG_FAILED;
        g3_usb_zeroize();
        eye_session_error(&session);
        phase = FAULT;
        return status;
    }

    /* End the old stream before a new host process performs a fresh handshake. */
    g3_usb_zeroize();
    eye_session_error(&session);
    phase = WAIT_HELLO;
    g6_camera_fault_diag.state = G6_CAMERA_DIAG_RECOVERED;
    return 0xffffffffU; /* Reuse the existing capture-error/no-frame path. */
}
