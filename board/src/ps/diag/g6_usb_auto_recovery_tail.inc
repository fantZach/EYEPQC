int g3_usb_capture(const uint8_t **data, unsigned *size);
int usb_cdc_clear_control_queue(void);

static int g6_auto_capture_hook(const uint8_t **data, unsigned *size)
{
    int status = g3_usb_capture(data, size);
    if (status == 0) {
        g6_auto_recovery_diag.malformed_drop_count = 0;
        return 0;
    }
    if (status == 15U) {
        g6_auto_recovery_diag.malformed_drop_count++;
        if (g6_auto_action_for_status(status,
                g6_auto_recovery_diag.malformed_drop_count) == G6_AUTO_ACTION_FAIL_CLOSED)
            return 16U;
        return status;
    }
    if (status == 16U) return 16U;
    if (status != 14U) return status;

    g6_auto_recovery_diag.state = 1;
    g6_auto_recovery_diag.recovery_status = (uint32_t)(
        secure_cleanup() ? 1 : g6_candidate_recover_camera());
    if (g6_auto_recovery_diag.recovery_status) {
        g6_auto_recovery_diag.state = 3;
        return 16U;
    }

    /* The old DDR/PL/session state is retired before another HELLO can be accepted. */
    eye_session_error(&session);
    clear_handshake_cache();
    frame_id = 0;
    phase = WAIT_HELLO;
    return G6_AUTO_RECOVERED;
}
