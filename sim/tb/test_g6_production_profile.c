/* Compile the real G6 source with G6_PRODUCTION and exercise provider gates. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "session.h"
#include "protocol.h"
#include "g6_secure_cleanup.h"

#define main g6_usb_firmware_main
#include "../../src/ps/src/g6_usb.c"
#undef main

static int provider_init_status;
static int provider_read_status;
static int provider_entropy_status;
static int provider_decapsulate_status;
static uint8_t provider_key_value;
static unsigned provider_init_calls;
static unsigned provider_shutdown_calls;
static unsigned provider_public_key_calls;
static unsigned provider_entropy_calls;
static unsigned decapsulation_calls;
static unsigned usb_send_calls;
static uint8_t last_send[1040];
static unsigned last_send_length;
volatile struct g6_secure_cleanup_diag g6_secure_cleanup_diag = {
    .magic = G6_SECURE_CLEANUP_MAGIC
};
static unsigned cleanup_stop_calls;
static unsigned cleanup_wipe_calls;
static unsigned cleanup_usb_calls;
static unsigned cleanup_order;
static int cleanup_stop_status;
static int cleanup_wipe_status;
static int cleanup_usb_status;
static int camera_init_status;
static int cdc_init_status;
static unsigned camera_init_calls;
static unsigned cdc_init_calls;

int g6_production_security_init(void)
{
    ++provider_init_calls;
    return provider_init_status;
}

int g6_production_read_mlkem512_public_key(uint8_t out[800])
{
    ++provider_public_key_calls;
    memset(out, provider_key_value, 800U);
    if (provider_read_status) out[0] ^= 0xffU; /* simulate partial/error output */
    return provider_read_status;
}

int g6_production_mlkem512_decapsulate(uint8_t shared[32],
                                      const uint8_t ciphertext[768],
                                      const uint8_t expected_public_key_hash[32])
{
    uint8_t public_key[800], current_hash[32];
    (void)ciphertext;
    memset(public_key, provider_key_value, sizeof public_key);
    int status = eye_sha256(current_hash, public_key, sizeof public_key);
    for (unsigned i = 0; !status && i < sizeof current_hash; ++i)
        if (current_hash[i] != expected_public_key_hash[i]) status = 1;
    memset(shared, 0xee, 32U); /* model a partial provider output on every path */
    if (!status) {
        ++decapsulation_calls;
        if (!provider_decapsulate_status) memset(shared, 0x41, 32U);
        else status = provider_decapsulate_status;
    }
    memset(current_hash, 0, sizeof current_hash);
    memset(public_key, 0, sizeof public_key);
    return status;
}

int g6_production_entropy_bytes(uint8_t *out, uint32_t length)
{
    ++provider_entropy_calls;
    memset(out, 0xa7, length);
    return provider_entropy_status;
}

void g6_production_security_shutdown(void)
{
    ++provider_shutdown_calls;
}

int usb_cdc_send(uint8_t *data, uint32_t size)
{
    if (size > sizeof last_send) return 1;
    ++usb_send_calls;
    last_send_length = size;
    memcpy(last_send, data, size);
    return 0;
}

int usb_cdc_take_control(uint8_t *out, uint32_t capacity)
{
    (void)out;
    (void)capacity;
    return 0;
}

int usb_cdc_init(void) { ++cdc_init_calls; return cdc_init_status; }
int usb_cdc_ready(void) { return 0; }
uint32_t usb_cdc_connection_epoch(void) { return 0U; }
int g3_usb_flush(void) { return 0; }
void g3_usb_zeroize(void) { }
int g3_usb_init(unsigned camera_cfg)
{
    (void)camera_cfg;
    ++camera_init_calls;
    return camera_init_status;
}
int g3_usb_capture(const uint8_t **data, unsigned *size)
{
    (void)data;
    (void)size;
    return 1;
}
int g3_usb_resume(void) { return 0; }
int g3_usb_cleanup_stop_dma_and_clear_gcm(void)
{
    if (cleanup_order++ != 0U) return 91;
    ++cleanup_stop_calls;
    return cleanup_stop_status;
}
int g3_usb_cleanup_wipe_frame_and_sealed(void)
{
    if (cleanup_order++ != 1U) return 92;
    ++cleanup_wipe_calls;
    return cleanup_wipe_status;
}
int usb_cdc_secure_cleanup_tx(uint8_t *buffer, unsigned capacity)
{
    if (cleanup_order++ != 2U || capacity != G6_SECURE_TX_CAPACITY) return 93;
    ++cleanup_usb_calls;
    memset(buffer, 0, capacity);
    return cleanup_usb_status;
}
void Xil_DCacheFlushRange(UINTPTR address, unsigned length)
{
    (void)address;
    (void)length;
}
int g3_usb_encrypt(const uint8_t *plain, unsigned size, const uint8_t aad[40],
                   const uint8_t key[16], uint32_t epoch, uint64_t sequence,
                   const uint8_t **sealed)
{
    (void)plain;
    (void)size;
    (void)aad;
    (void)key;
    (void)epoch;
    (void)sequence;
    (void)sealed;
    return 1;
}
int xil_printf(const char *format, ...) { (void)format; return 0; }

static void reset_provider(void)
{
    provider_init_status = 0;
    provider_read_status = 0;
    provider_entropy_status = 0;
    provider_decapsulate_status = 0;
    provider_key_value = 0x5aU;
    provider_init_calls = provider_shutdown_calls = provider_public_key_calls = 0U;
    provider_entropy_calls = decapsulation_calls = usb_send_calls = 0U;
    cleanup_stop_calls = cleanup_wipe_calls = cleanup_usb_calls = 0U;
    cleanup_order = 0U;
    cleanup_stop_status = cleanup_wipe_status = cleanup_usb_status = 0;
    camera_init_status = cdc_init_status = 0;
    camera_init_calls = cdc_init_calls = 0U;
    memset((void *)&g6_secure_cleanup_diag, 0, sizeof g6_secure_cleanup_diag);
    g6_secure_cleanup_diag.magic = G6_SECURE_CLEANUP_MAGIC;
    last_send_length = 0U;
    memset(last_send, 0, sizeof last_send);
    memset(&session, 0, sizeof session);
    memset(hello, 0, sizeof hello);
    memset(ack, 0, sizeof ack);
    phase = WAIT_HELLO;
}

static int test_missing_provider_fails_closed(void)
{
    reset_provider();
    provider_init_status = 7;
    if (initialize_production_security() == 0 || provider_init_calls != 1U ||
        provider_public_key_calls != 0U || provider_shutdown_calls != 1U)
        return 1;
    reset_provider();
    provider_entropy_status = 6;
    if (initialize_production_security() == 0 || provider_entropy_calls != 1U ||
        provider_public_key_calls != 0U || provider_shutdown_calls != 1U ||
        production_drbg.instantiated)
        return 4;
    reset_provider();
    provider_read_status = 8;
    if (initialize_production_startup() == 0 || provider_public_key_calls != 1U ||
        provider_shutdown_calls != 1U || production_drbg.instantiated ||
        phase != FAULT || camera_init_calls || cdc_init_calls)
        return 2;
    return 0;
}

static int make_hello(uint8_t message[48])
{
    uint8_t body[36] = {1U, 1U, 0U, 1U};
    for (unsigned i = 0; i < 32U; ++i) body[4U + i] = (uint8_t)(i + 1U);
    return eye_control_encode(message, 48U, EYE_HELLO, body, sizeof body);
}

static int make_kem(uint8_t message[780])
{
    uint8_t ciphertext[768] = {0};
    return eye_control_encode(message, 780U, EYE_KEM_CIPHERTEXT,
                              ciphertext, sizeof ciphertext);
}

static int test_random_failure_sends_no_ack(void)
{
    uint8_t message[48], output[32];
    reset_provider();
    if (initialize_production_security() || make_hello(message)) return 1;
    production_drbg.reseed_counter = EYE_HMAC_DRBG_RESEED_INTERVAL + 1U;
    provider_entropy_status = 9;
    memset(output, 0xcc, sizeof output);
    if (board_random(output, message) == 0 || provider_entropy_calls != 2U)
        return 2;
    for (unsigned i = 0; i < sizeof output; ++i)
        if (output[i] != 0U) return 3;
    if (handle_control(message, sizeof message) == 0 || phase != FAULT ||
        usb_send_calls != 0U || provider_shutdown_calls != 1U ||
        production_drbg.instantiated || cleanup_stop_calls != 1U ||
        cleanup_wipe_calls != 1U || cleanup_usb_calls != 1U || cleanup_order != 3U ||
        g6_secure_cleanup_diag.stage != G6_CLEANUP_COMPLETE)
        return 4;
    return 0;
}

static int test_cleanup_failure_stays_fail_closed(void)
{
    reset_provider();
    if (initialize_production_security()) return 1;
    cleanup_wipe_status = 1;
    fail_closed();
    if (phase != FAULT || provider_shutdown_calls != 1U ||
        production_drbg.instantiated || cleanup_stop_calls != 1U ||
        cleanup_wipe_calls != 1U || cleanup_usb_calls != 0U ||
        g6_secure_cleanup_diag.stage != G6_CLEANUP_FAILED ||
        g6_secure_cleanup_diag.failed_stage != G6_CLEANUP_FRAME_AND_SEALED)
        return 2;
    return 0;
}

static int test_disconnect_uses_secure_cleanup_without_auto_recovery(void)
{
    reset_provider();
    g6_disconnects = 0U;
    g6_transport_errors = 0U;
    if (initialize_production_security()) return 1;
    phase = STREAM;
    session.state = EYE_STATE_STREAMING;
    if (retire_disconnected_session(7U, 8U, 0U, 9U) != 0 ||
        phase != WAIT_HELLO || g6_disconnects != 1U || g6_transport_errors != 0U ||
        cleanup_stop_calls != 1U || cleanup_wipe_calls != 1U ||
        cleanup_usb_calls != 1U || cleanup_order != 3U ||
        g6_secure_cleanup_diag.stage != G6_CLEANUP_COMPLETE)
        return 2;

    reset_provider();
    g6_disconnects = 0U;
    g6_transport_errors = 0U;
    if (initialize_production_security()) return 3;
    phase = STREAM;
    session.state = EYE_STATE_STREAMING;
    cleanup_usb_status = 1;
    if (retire_disconnected_session(7U, 8U, 0U, 9U) != 1 ||
        phase != FAULT || g6_disconnects != 0U || g6_transport_errors != 1U ||
        cleanup_stop_calls != 1U || cleanup_wipe_calls != 1U ||
        cleanup_usb_calls != 1U || cleanup_order != 3U ||
        g6_secure_cleanup_diag.stage != G6_CLEANUP_FAILED ||
        g6_secure_cleanup_diag.failed_stage != G6_CLEANUP_USB_TX_QUIESCE)
        return 4;

    reset_provider();
    g6_disconnects = 0U;
    if (initialize_production_security()) return 5;
    fail_closed();
    if (phase != FAULT || provider_shutdown_calls != 1U || cleanup_order != 3U)
        return 6;
    if (retire_disconnected_session(7U, 8U, 0U, 9U) != 1 ||
        phase != FAULT || g6_disconnects != 0U || provider_shutdown_calls != 1U ||
        cleanup_stop_calls != 1U || cleanup_wipe_calls != 1U ||
        cleanup_usb_calls != 1U || cleanup_order != 3U)
        return 7;
    return 0;
}

static int test_pinned_key_and_provider_random(void)
{
    uint8_t hello_message[48], kem_message[780], shared[32];
    reset_provider();
    if (initialize_production_security() || make_hello(hello_message)) return 1;
    if (handle_control(hello_message, sizeof hello_message) ||
        phase != WAIT_KEM || usb_send_calls != 1U ||
        provider_entropy_calls != 1U || last_send_length != 51U)
        return 2;

    /* A provider returning a different device identity must not decapsulate. */
    if (make_kem(kem_message)) return 3;
    provider_key_value = 0x33U;
    memset(shared, 0xcc, sizeof shared);
    if (production_decapsulate(shared, kem_message + 12U) == 0 ||
        decapsulation_calls != 0U)
        return 4;
    for (unsigned i = 0; i < sizeof shared; ++i)
        if (shared[i]) return 5;

    /* Start a fresh session; opaque provider decapsulation exports no private key. */
    reset_provider();
    if (initialize_production_security() || make_hello(hello_message) ||
        make_kem(kem_message)) return 6;
    if (handle_control(hello_message, sizeof hello_message) ||
        handle_control(kem_message, sizeof kem_message) ||
        phase != WAIT_FINISHED || provider_public_key_calls != 1U ||
        decapsulation_calls != 1U || usb_send_calls != 2U ||
        provider_entropy_calls != 1U)
        return 7;

    memset(shared, 0xcc, sizeof shared);
    provider_decapsulate_status = 9;
    if (production_decapsulate(shared, kem_message + 12U) == 0 ||
        decapsulation_calls != 2U)
        return 8;
    for (unsigned i = 0; i < sizeof shared; ++i)
        if (shared[i]) return 9;
    return 0;
}

static int test_startup_failure_wipes_cpu_owned_secrets(void)
{
    reset_provider();
    memset(&session, 0xa1, sizeof session);
    memset(hello, 0xd4, sizeof hello);
    memset(ack, 0xe5, sizeof ack);
    memset(tx, 0xf6, sizeof tx);
    phase = STREAM;
    provider_init_status = 40;
    if (initialize_production_startup() != 40 || provider_init_calls != 1U ||
        camera_init_calls != 0U || cdc_init_calls != 0U ||
        provider_shutdown_calls != 1U || production_drbg.instantiated ||
        phase != FAULT || cleanup_usb_calls != 0U)
        return 1;
    for (unsigned i = 0; i < sizeof session; ++i)
        if (((const uint8_t *)&session)[i]) return 2;
    for (unsigned i = 0; i < sizeof hello; ++i)
        if (hello[i] || ack[i]) return 3;
    for (unsigned i = 0; i < sizeof tx; ++i)
        if (tx[i]) return 4;

    reset_provider();
    memset(hello, 0xd4, sizeof hello);
    memset(ack, 0xe5, sizeof ack);
    memset(tx, 0xf6, sizeof tx);
    phase = STREAM;
    camera_init_status = 41;
    if (initialize_production_startup() != 41 || provider_init_calls != 1U ||
        camera_init_calls != 1U ||
        cdc_init_calls != 0U || provider_shutdown_calls != 1U ||
        production_drbg.instantiated || phase != FAULT || cleanup_usb_calls != 0U)
        return 5;
    for (unsigned i = 0; i < sizeof session; ++i)
        if (((const uint8_t *)&session)[i]) return 6;
    for (unsigned i = 0; i < sizeof hello; ++i)
        if (hello[i] || ack[i]) return 7;
    for (unsigned i = 0; i < sizeof tx; ++i)
        if (tx[i]) return 8;

    reset_provider();
    memset(hello, 0xd4, sizeof hello);
    memset(ack, 0xe5, sizeof ack);
    memset(tx, 0xf6, sizeof tx);
    cdc_init_status = 42;
    if (initialize_production_startup() != 42 || provider_init_calls != 1U ||
        camera_init_calls != 1U ||
        cdc_init_calls != 1U || provider_shutdown_calls != 1U ||
        production_drbg.instantiated || phase != FAULT || cleanup_usb_calls != 0U)
        return 9;
    for (unsigned i = 0; i < sizeof session; ++i)
        if (((const uint8_t *)&session)[i]) return 10;
    for (unsigned i = 0; i < sizeof hello; ++i)
        if (hello[i] || ack[i]) return 11;
    for (unsigned i = 0; i < sizeof tx; ++i)
        if (tx[i]) return 12;

    reset_provider();
    if (initialize_production_startup() != 0 || provider_init_calls != 1U ||
        camera_init_calls != 1U || cdc_init_calls != 1U ||
        provider_shutdown_calls != 0U || phase == FAULT)
        return 13;
    return 0;
}

int main(void)
{
    int status = test_missing_provider_fails_closed();
    if (!status) status = test_random_failure_sends_no_ack();
    if (!status) status = test_cleanup_failure_stays_fail_closed();
    if (!status) status = test_disconnect_uses_secure_cleanup_without_auto_recovery();
    if (!status) status = test_pinned_key_and_provider_random();
    if (!status) status = test_startup_failure_wipes_cpu_owned_secrets();
    if (status) {
        fprintf(stderr, "g6_production_profile_failed=%d\n", status);
        return 1;
    }
    puts("G6_PRODUCTION_PROFILE_PASS entropy_fail_closed=1 reseed_failure_no_ack=1 cleanup_order=1 cleanup_failure_fail_closed=1 disconnect_cleanup_without_recovery=1 key_identity_pinned=1 opaque_key_decapsulation=1 startup_single_pass=1 startup_failure_wipe=1");
    return 0;
}
