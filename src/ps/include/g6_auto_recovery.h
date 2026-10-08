#ifndef EYEPQC_G6_AUTO_RECOVERY_H
#define EYEPQC_G6_AUTO_RECOVERY_H

#include <stdint.h>

#define G6_AUTO_MAGIC 0x47415231U
#define G6_AUTO_RECOVERED (-2)
#define G6_AUTO_MALFORMED_DROP_LIMIT 3U

enum g6_auto_capture_observation {
    G6_AUTO_CAPTURE_NONE = 0,
    G6_AUTO_CAPTURE_TRANSFER_START_FAILED = 1,
    G6_AUTO_CAPTURE_DMA_IRQ_ERROR = 2,
    G6_AUTO_CAPTURE_BUSY_TIMEOUT = 3,
    G6_AUTO_CAPTURE_OK = 4,
    G6_AUTO_CAPTURE_MALFORMED_JPEG = 5,
    G6_AUTO_CAPTURE_GUARD_BROKEN = 6
};

enum g6_auto_trigger_mode {
    G6_AUTO_TRIGGER_NONE = 0,
    G6_AUTO_TRIGGER_CAMERA_RESET = 1,
    G6_AUTO_TRIGGER_ROUTING_STALL = 2
};

enum g6_auto_action {
    G6_AUTO_ACTION_DROP = 0,
    G6_AUTO_ACTION_RECOVER = 1,
    G6_AUTO_ACTION_FAIL_CLOSED = 2
};

/* Shared by firmware and offline tests; status 14 is reported in detail by observation. */
static inline enum g6_auto_action g6_auto_action_for_status(unsigned status,
                                                            unsigned consecutive_malformed)
{
    if (status == 14U) return G6_AUTO_ACTION_RECOVER;
    if (status == 15U)
        return consecutive_malformed <= G6_AUTO_MALFORMED_DROP_LIMIT
                   ? G6_AUTO_ACTION_DROP : G6_AUTO_ACTION_FAIL_CLOSED;
    if (status == 16U) return G6_AUTO_ACTION_FAIL_CLOSED;
    return G6_AUTO_ACTION_FAIL_CLOSED;
}

struct g6_auto_recovery_diag {
    uint32_t magic;
    volatile uint32_t state;
    volatile uint32_t stage;
    volatile uint32_t trigger_mode;
    volatile uint32_t observation;
    volatile uint32_t status_register;
    volatile uint32_t busy_at_start;
    volatile uint32_t busy_at_end;
    volatile uint32_t elapsed_us;
    volatile uint32_t recovery_status;
    volatile uint32_t camera_status;
    volatile uint32_t frame_length;
    volatile uint32_t recovery_count;
    volatile uint32_t malformed_drop_count;
};

/* Snapshot of the first transport failure; separate from the live counters. */
struct g6_transport_failure_diag {
    volatile uint32_t send_status;
    volatile uint32_t resume_status;
    volatile uint32_t phase;
    volatile uint32_t usb_ready;
    volatile uint32_t connection_epoch;
    volatile uint32_t last_successful_frame_id;
    volatile uint32_t transport_error_count;
    volatile uint32_t reserved;
};

extern volatile struct g6_auto_recovery_diag g6_auto_recovery_diag;
extern volatile struct g6_transport_failure_diag g6_transport_failure_diag;
extern volatile uint32_t g6_auto_recovery_request;

#endif
