/* Candidate-only USB probe wrapper to clear buffered pre-recovery control messages. */
#include "usb_probe.c"

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
