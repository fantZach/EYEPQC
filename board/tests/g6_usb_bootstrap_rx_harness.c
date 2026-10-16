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
    puts("G6_BOOTSTRAP_ACTUAL_RX_WIPE_PASS partial_query_retry=1 partial_data_fault=1");
    return 0;
}
