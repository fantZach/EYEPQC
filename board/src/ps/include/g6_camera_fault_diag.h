#ifndef EYEPQC_G6_CAMERA_FAULT_DIAG_H
#define EYEPQC_G6_CAMERA_FAULT_DIAG_H

#include <stdint.h>

#define G6_CAMERA_DIAG_MAGIC 0x47434431U

enum g6_camera_diag_state {
    G6_CAMERA_DIAG_IDLE = 0,
    G6_CAMERA_DIAG_RUNNING = 1,
    G6_CAMERA_DIAG_RECOVERED = 2,
    G6_CAMERA_DIAG_FAILED = 3
};

struct g6_camera_fault_diag {
    uint32_t magic;
    volatile uint32_t state;
    volatile uint32_t stage;
    volatile uint32_t result;
    volatile uint32_t camera_stopped_status;
    volatile uint32_t capture_sr_armed;
    volatile uint32_t capture_busy_armed;
    volatile uint32_t capture_sr_timeout;
    volatile uint32_t capture_busy_timeout;
    volatile uint32_t timeout_us;
    volatile uint32_t reset_status;
    volatile uint32_t camera_recovered_status;
    volatile uint32_t recovered_frame_length;
    volatile uint32_t recovered_frame_hash;
};

#endif
