/* Offline harness calls the real firmware activation/control/cleanup functions. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#define main firmware_main
#include "../src/ps/src/g6_usb.c"
#undef main
extern int eye_mlkem_keypair_derand(uint8_t *, uint8_t *, const uint8_t *);
volatile struct g6_secure_cleanup_diag g6_secure_cleanup_diag;
static uint64_t fake_now;
static uint32_t fake_epoch = 7U;
static unsigned rx_clears;
static int change_epoch_during_activation;
static int send_result, disconnect_after_send;
static int fake_ready = 1, drop_dtr_after_send, cleanup_failure;
static unsigned query_trace_count;
static uint8_t last_send[128];
static uint8_t material[EYE_BOOT_TOTAL], public_key[800];
int xil_printf(const char *f, ...) {
    if (!strcmp(f, "G6_DEV_USB_QUERY state=%u epoch=%lu\r\n") ||
            !strcmp(f, "G6_DEV_USB_QUERY_TX result=%d ready=%u epoch=%lu\r\n"))
        ++query_trace_count;
    return 0;
}
uint32_t Xil_In32(uintptr_t p) { assert(p == 0xf800025cU); return 5; }
void XTime_GetTime(XTime *p) { *p = fake_now * 1000U; }
void Xil_DCacheFlushRange(uintptr_t p, unsigned n) { (void)p; (void)n; }
int usb_cdc_ready(void) { return fake_ready; }
uint32_t usb_cdc_connection_epoch(void) {
    if (change_epoch_during_activation && usb_bootstrap.received == EYE_BOOT_TOTAL) {
        change_epoch_during_activation = 0;
        ++fake_epoch;
    }
    return fake_epoch;
}
int usb_cdc_bootstrap_rx_pending(void) { return 0; }
int usb_cdc_bootstrap_rx_interrupted(void) { return 0; }
void usb_cdc_bootstrap_rx_clear(void) { ++rx_clears; }
int usb_cdc_send(uint8_t *p, uint32_t n) {
    assert(n == EYE_BOOT_ACK + 3U && p[0] == 1U);
    memcpy(last_send, p, n);
    if (disconnect_after_send) ++fake_epoch;
    if (drop_dtr_after_send) fake_ready = 0;
    return send_result;
}
int g3_usb_cleanup_stop_dma_and_clear_gcm(void) { return 0; }
int g3_usb_cleanup_wipe_frame_and_sealed(void) { return 0; }
int usb_cdc_secure_cleanup_tx(uint8_t *p, unsigned n) {
    memset(p, 0, n); return cleanup_failure;
}
int g3_usb_flush(void) { return 0; }
int usb_cdc_take_control(uint8_t *p, uint32_t n) { (void)p; (void)n; return 0; }
int usb_cdc_init(void) { return 0; }
int g3_usb_init(unsigned cfg) { (void)cfg; return 0; }
int g3_usb_capture(const uint8_t **p, unsigned *n) { (void)p; (void)n; return 1; }
int g3_usb_resume(void) { return 0; }
void g3_usb_zeroize(void) { }
int g3_usb_encrypt(const uint8_t *p, unsigned n, const uint8_t aad[40],
                   const uint8_t key[16], uint32_t epoch, uint64_t sequence,
                   const uint8_t **out) {
    (void)p; (void)n; (void)aad; (void)key; (void)epoch; (void)sequence; (void)out;
    return 1;
}
static int zero(const void *p, unsigned n) {
    const uint8_t *s = p; while (n--) if (*s++) return 0; return 1;
}
static void fresh(void) {
    memset(&usb_bootstrap, 0, sizeof usb_bootstrap);
    memset(&session, 0, sizeof session);
    memset(private_key, 0, sizeof private_key);
    memset(random_seed, 0, sizeof random_seed);
    phase = WAIT_HELLO; rx_clears = 0; fake_now = 100;
    change_epoch_during_activation = 0;
    send_result = disconnect_after_send = 0;
    drop_dtr_after_send = cleanup_failure = 0; fake_ready = 1;
    query_trace_count = 0;
}
static unsigned message(uint8_t *out, unsigned type, unsigned offset, unsigned length) {
    memcpy(out, "EYBS", 4); out[4] = 1; out[5] = type;
    eye_boot_put16(out + 6, offset); eye_boot_put16(out + 8, length);
    eye_boot_put16(out + 10, EYE_BOOT_TOTAL);
    if (length) memcpy(out + 12, material + offset, length);
    return length + 12;
}
static void faulted(void) {
    assert(usb_bootstrap.state == EYE_BOOT_FAULT && phase == FAULT);
    assert(!usb_bootstrap.received && zero(usb_bootstrap.material, EYE_BOOT_TOTAL));
    assert(zero(private_key, sizeof private_key) && zero(random_seed, 32));
    assert(random_counter == 0 && rx_clears);
}
int main(void) {
    uint8_t coins[64] = {0}, sk[1632], packet[1036];
    assert(!eye_mlkem_keypair_derand(public_key, sk, coins));
    assert(!eye_sha256(material, public_key, 800));
    memcpy(material + 32, sk, sizeof sk); memset(material + 1664, 0x5b, 32);
    fresh(); send_result = disconnect_after_send = 1;
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(usb_bootstrap.state == EYE_BOOT_WAIT && phase == WAIT_HELLO);
    assert(query_trace_count == 2);
    assert(zero(private_key, sizeof private_key) && zero(random_seed, 32));
    send_result = disconnect_after_send = 0;
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(last_send[15] == EYE_BOOT_WAIT);
    fresh(); send_result = drop_dtr_after_send = 1;
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(usb_bootstrap.state == EYE_BOOT_WAIT && phase == WAIT_HELLO);
    fresh();
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(last_send[15] == EYE_BOOT_WAIT && zero(last_send + 17, 32));
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    assert(usb_bootstrap.state == EYE_BOOT_RECV && usb_bootstrap.received == 1024);
    assert(zero(last_send + 17, 32));
    assert(!bootstrap_control(packet, message(packet, 2, 1024, 672)));
    assert(usb_bootstrap.state == EYE_BOOT_READY && usb_bootstrap.received == 1696);
    assert(!memcmp(private_key, sk, 1632) && !memcmp(random_seed, material + 1664, 32));
    assert(!memcmp(last_send + 17, material, 32) && zero(usb_bootstrap.material, 1696));
    phase = STREAM; session.video_key[0] = 0x34;
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(phase == STREAM && session.video_key[0] == 0x34);
    assert(!retire_disconnected_session(UINT32_MAX, 0U, 0U, ++fake_epoch));
    assert(usb_bootstrap.state == EYE_BOOT_READY && !memcmp(private_key, sk, 1632));
    send_result = disconnect_after_send = 1;
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(usb_bootstrap.state == EYE_BOOT_READY && phase == WAIT_HELLO);
    assert(!memcmp(private_key, sk, 1632));
    send_result = disconnect_after_send = 0;
    assert(bootstrap_control(packet, message(packet, 2, 0, 1)));
    faulted();
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(last_send[15] == EYE_BOOT_FAULT && zero(last_send + 17, 32));
    assert(bootstrap_control(packet, message(packet, 2, 0, 1024))); faulted();
    fresh();
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    send_result = disconnect_after_send = 1;
    assert(bootstrap_control(packet, message(packet, 1, 0, 0))); faulted();
    fresh(); send_result = 1;
    assert(bootstrap_control(packet, message(packet, 1, 0, 0))); faulted();
    fresh();
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    send_result = disconnect_after_send = 1;
    assert(!bootstrap_control(packet, message(packet, 2, 1024, 672)));
    assert(usb_bootstrap.state == EYE_BOOT_READY && phase == WAIT_HELLO);
    assert(!memcmp(private_key, sk, 1632) && !memcmp(random_seed, material + 1664, 32));
    send_result = 2; disconnect_after_send = 0;
    assert(bootstrap_control(packet, message(packet, 1, 0, 0))); faulted();
    fresh(); send_result = disconnect_after_send = 1;
    assert(bootstrap_control(packet, message(packet, 2, 0, 1024))); faulted();
    fresh();
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    assert(!bootstrap_control(packet, message(packet, 2, 1024, 672)));
    send_result = 1;
    assert(bootstrap_control(packet, message(packet, 1, 0, 0))); faulted();
    fresh();
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    assert(!bootstrap_control(packet, message(packet, 2, 1024, 672)));
    send_result = drop_dtr_after_send = 1;
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(usb_bootstrap.state == EYE_BOOT_READY && phase == WAIT_HELLO);
    assert(!memcmp(private_key, sk, 1632));
    fake_ready = 1; drop_dtr_after_send = 0;
    disconnect_after_send = cleanup_failure = 1;
    assert(bootstrap_control(packet, message(packet, 1, 0, 0))); faulted();
    for (int error = 4; error <= 5; ++error) {
        fresh();
        assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
        assert(!bootstrap_control(packet, message(packet, 2, 1024, 672)));
        send_result = error;
        assert(bootstrap_control(packet, message(packet, 1, 0, 0))); faulted();
    }
    for (unsigned bad = 0; bad < 7; ++bad) {
        fresh(); unsigned n = message(packet, 2, 0, 1024);
        if (bad == 0) packet[0] ^= 1;
        if (bad == 1) packet[4] = 2;
        if (bad == 2) packet[5] = 0x81;
        if (bad == 3) packet[7] = 1;
        if (bad == 4) packet[9]--;
        if (bad == 5) packet[11]--;
        if (bad == 6) n = 11;
        assert(bootstrap_control(packet, n)); faulted();
    }
    fresh();
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    fake_now += 9999;
    assert(!bootstrap_control(packet, message(packet, 1, 0, 0)));
    assert(eye_boot_tick(&usb_bootstrap, fake_now + 1, fake_epoch, 1));
    mark_fault(); faulted();
    fresh(); assert(!eye_boot_tick(&usb_bootstrap, 50, fake_epoch + 1, 0));
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    assert(eye_boot_tick(&usb_bootstrap, fake_now, fake_epoch + 1, 1));
    mark_fault(); faulted();
    fresh(); material[0] ^= 1;
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    assert(bootstrap_control(packet, message(packet, 2, 1024, 672))); faulted();
    material[0] ^= 1;
    fresh();
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    change_epoch_during_activation = 1;
    assert(bootstrap_control(packet, message(packet, 2, 1024, 672))); faulted();
    fresh(); material[32 + 1568] ^= 1;
    assert(!bootstrap_control(packet, message(packet, 2, 0, 1024)));
    assert(bootstrap_control(packet, message(packet, 2, 1024, 672))); faulted();
    puts("G6_USB_BOOTSTRAP_REAL_FIRMWARE_PASS actual_mlkem=1 ready_query_session_unchanged=1 one_shot=1 timeout=1 disconnect=1 secret_wipe=1");
    return 0;
}
