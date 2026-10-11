/* Compile the real G6 source with G6_PRODUCTION and exercise provider gates. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "session.h"
#include "protocol.h"

#define main g6_usb_firmware_main
#include "../../src/ps/src/g6_usb.c"
#undef main

static int provider_init_status;
static int provider_read_status;
static int provider_entropy_status;
static uint8_t provider_key_value;
static unsigned provider_init_calls;
static unsigned provider_shutdown_calls;
static unsigned provider_read_calls;
static unsigned provider_entropy_calls;
static unsigned decapsulation_calls;
static unsigned usb_send_calls;
static uint8_t last_send[1040];
static unsigned last_send_length;

int g6_production_security_init(void)
{
    ++provider_init_calls;
    return provider_init_status;
}

int g6_production_read_mlkem512_private_key(uint8_t out[1632])
{
    ++provider_read_calls;
    memset(out, provider_key_value, 1632U);
    if (provider_read_status) out[0] ^= 0xffU; /* simulate partial/error output */
    return provider_read_status;
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

int eye_mlkem_check_sk(const uint8_t sk[1632])
{
    for (unsigned i = 0; i < 1632U; ++i)
        if (sk[i] != provider_key_value) return 1;
    return 0;
}

int eye_mlkem_dec(uint8_t shared[32], const uint8_t ciphertext[768],
                  const uint8_t secret_key[1632])
{
    (void)ciphertext;
    if (eye_mlkem_check_sk(secret_key)) return 1;
    ++decapsulation_calls;
    memset(shared, 0x41, 32U);
    return 0;
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

int usb_cdc_init(void) { return 0; }
int usb_cdc_ready(void) { return 0; }
uint32_t usb_cdc_connection_epoch(void) { return 0U; }
int g3_usb_flush(void) { return 0; }
void g3_usb_zeroize(void) { }
int g3_usb_init(unsigned camera_cfg) { (void)camera_cfg; return 0; }
int g3_usb_capture(const uint8_t **data, unsigned *size)
{
    (void)data;
    (void)size;
    return 1;
}
int g3_usb_resume(void) { return 0; }
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
    provider_key_value = 0x5aU;
    provider_init_calls = provider_shutdown_calls = provider_read_calls = 0U;
    provider_entropy_calls = decapsulation_calls = usb_send_calls = 0U;
    last_send_length = 0U;
    memset(last_send, 0, sizeof last_send);
    memset(&session, 0, sizeof session);
    memset(hello, 0, sizeof hello);
    memset(ack, 0, sizeof ack);
    phase = WAIT_HELLO;
}

static int test_missing_provider_fails_closed(void)
{
    uint8_t key[1632];
    memset(key, 0x99, sizeof key);
    reset_provider();
    provider_init_status = 7;
    if (initialize_production_security() == 0 || provider_init_calls != 1U ||
        provider_read_calls != 0U || provider_shutdown_calls != 1U)
        return 1;
    reset_provider();
    provider_entropy_status = 6;
    if (initialize_production_security() == 0 || provider_entropy_calls != 1U ||
        provider_read_calls != 0U || provider_shutdown_calls != 1U ||
        production_drbg.instantiated)
        return 4;
    reset_provider();
    provider_read_status = 8;
    if (production_load_key(key) == 0 || provider_read_calls != 1U)
        return 2;
    for (unsigned i = 0; i < sizeof key; ++i)
        if (key[i] != 0U) return 3;
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
        production_drbg.instantiated)
        return 4;
    return 0;
}

static int test_pinned_key_and_provider_random(void)
{
    uint8_t hello_message[48], kem_message[780];
    reset_provider();
    if (initialize_production_security() || make_hello(hello_message)) return 1;
    if (handle_control(hello_message, sizeof hello_message) ||
        phase != WAIT_KEM || usb_send_calls != 1U ||
        provider_entropy_calls != 1U || last_send_length != 51U)
        return 2;

    /* A provider returning a different device identity must not decapsulate. */
    if (make_kem(kem_message)) return 3;
    provider_key_value = 0x33U;
    if (handle_control(kem_message, sizeof kem_message) == 0 ||
        decapsulation_calls != 0U)
        return 4;

    /* Start a fresh session with the pinned key; each KEM reloads via provider. */
    reset_provider();
    if (initialize_production_security() || make_hello(hello_message) ||
        make_kem(kem_message)) return 5;
    if (handle_control(hello_message, sizeof hello_message) ||
        handle_control(kem_message, sizeof kem_message) ||
        phase != WAIT_FINISHED || provider_read_calls != 2U ||
        decapsulation_calls != 1U || usb_send_calls != 2U ||
        provider_entropy_calls != 1U)
        return 6;
    return 0;
}

int main(void)
{
    int status = test_missing_provider_fails_closed();
    if (!status) status = test_random_failure_sends_no_ack();
    if (!status) status = test_pinned_key_and_provider_random();
    if (status) {
        fprintf(stderr, "g6_production_profile_failed=%d\n", status);
        return 1;
    }
    puts("G6_PRODUCTION_PROFILE_PASS entropy_fail_closed=1 reseed_failure_no_ack=1 key_identity_pinned=1");
    return 0;
}
