/* Reuse SDK stubs, not the old harness main; no debugger/hardware calls. */
#define G6_DEV_USB_BOOTSTRAP 1
#define main legacy_fixture_main
#include "../../sim/tb/test_g6_usb_idle_fastpath.c"
#undef main
#include <assert.h>
static void push(const uint8_t *p, unsigned n) { while (n--) rx_push(*p++); }
int main(void) {
    uint8_t query[] = {1,0,12,'E','Y','B','S',1,1,0,0,0,0,6,0xa0};
    uint8_t data[] = {1,0,13,'E','Y','B','S',1,2,0,0,0,1,6,0xa0,0x89};
    uint8_t out[1036] = {0};
    usb_cdc_bootstrap_rx_clear();
    push(query, 8); (void)usb_cdc_take_control(out, sizeof out);
    rx_reset();
    assert(!usb_cdc_bootstrap_rx_interrupted());
    assert(bytes_are(rx_ring, sizeof rx_ring, 0) && bytes_are(control_record, sizeof control_record, 0));
    push(data, 9); rx_reset();
    assert(usb_cdc_bootstrap_rx_interrupted());
    usb_cdc_bootstrap_rx_clear();
    push(data, sizeof data);
    assert(usb_cdc_take_control(out, sizeof out) == 13 && out[12] == 0x89);
    assert(bytes_are(rx_ring, sizeof rx_ring, 0) && bytes_are(control_record, sizeof control_record, 0));
    rx_reset(); assert(usb_cdc_bootstrap_rx_interrupted());
    usb_cdc_bootstrap_rx_clear(); push(data, 12);
    assert(!usb_cdc_take_control(out, sizeof out));
    assert(usb_cdc_bootstrap_rx_pending()); rx_reset();
    assert(usb_cdc_bootstrap_rx_interrupted());
    assert(bytes_are(rx_ring, sizeof rx_ring, 0) && bytes_are(control_record, sizeof control_record, 0));
    usb_cdc_bootstrap_rx_clear();
    configured = dtr = 1; tx_pending = 0; connection_epoch = 7;
    mode = 'E'; test_epoch = 91; test_epoch_bytes = 2;
    XUsbPs_SetupData setup = {0};
    setup.bRequest = 0x22; setup.wValue = 3; /* DTR unchanged, RTS asserted. */
    push(query, sizeof query);
    XUsbPs_ClassReq(&usb, &setup);
    assert(connection_epoch == 7 && usb_cdc_ready());
    assert(usb_cdc_take_control(out, sizeof out) == 12);
    assert(mode == 'E' && test_epoch == 91 && test_epoch_bytes == 2);
    push(query, 8); assert(!usb_cdc_take_control(out, sizeof out));
    setup.wValue = 1; /* RTS cleared, DTR still unchanged. */
    XUsbPs_ClassReq(&usb, &setup);
    push(query + 8, sizeof query - 8);
    assert(usb_cdc_take_control(out, sizeof out) == 12);
    push(data, 12); assert(!usb_cdc_take_control(out, sizeof out));
    XUsbPs_ClassReq(&usb, &setup);
    push(data + 12, sizeof data - 12);
    assert(usb_cdc_take_control(out, sizeof out) == 13 && out[12] == 0x89);
    assert(!usb_cdc_bootstrap_rx_interrupted());
    /* A genuine DTR fall still clears CPU copies and marks interrupted DATA.
     * Leave endpoint rearming to its separate SDK fixture, not real MMIO. */
    configured = 0; setup.wValue = 0;
    XUsbPs_ClassReq(&usb, &setup);
    assert(!dtr && connection_epoch == 8 && usb_cdc_bootstrap_rx_interrupted());
    assert(bytes_are(rx_ring, sizeof rx_ring, 0) && bytes_are(control_record, sizeof control_record, 0));
    usb_cdc_bootstrap_rx_clear();
    push(query, sizeof query); setup.wValue = 1;
    XUsbPs_ClassReq(&usb, &setup);
    assert(dtr && connection_epoch == 9 && !usb_cdc_bootstrap_rx_pending());
    push(data, 9); usb_event(NULL, XUSBPS_IXR_UR_MASK);
    assert(!dtr && !configured && connection_epoch == 10);
    assert(usb_cdc_bootstrap_rx_interrupted());
    assert(bytes_are(rx_ring, sizeof rx_ring, 0) && bytes_are(control_record, sizeof control_record, 0));
    puts("G6_BOOTSTRAP_ACTUAL_RX_WIPE_PASS partial_query_retry=1 partial_data_fault=1");
    return 0;
}
