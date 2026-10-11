/* Branch harness around the real G6 static functions. It does not call main. */
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "session.h"
#include "protocol.h"
#include "g6_auto_recovery.h"
#include "g6_secure_cleanup.h"
#include "g6_rekey_diag.h"

#ifndef UINTPTR
#define UINTPTR uintptr_t
#endif

#define main g6_usb_firmware_main
#include "../../src/ps/src/g6_usb.c"
#undef main

volatile struct g6_secure_cleanup_diag g6_secure_cleanup_diag;
volatile struct g6_auto_recovery_diag g6_auto_recovery_diag;
static unsigned cleanup_diag_flush_calls;
static unsigned gcm_clear_calls;

void usb_cdc_g6_diag_fill(volatile struct g6_rekey_diag *diag)
{
    (void)diag;
}

void Xil_DCacheFlushRange(uintptr_t address, uint32_t length)
{
    if (address == (uintptr_t)&g6_secure_cleanup_diag &&
        length == sizeof g6_secure_cleanup_diag)
        ++cleanup_diag_flush_calls;
}

static unsigned cleanup_calls[3];
static unsigned cleanup_fail_at;
static unsigned cleanup_order[3];
static unsigned cleanup_order_count;
static int fake_usb_ready = 1;
static uint32_t fake_connection_epoch = 7U;
static unsigned usb_send_calls;
static uint8_t usb_last_send[1040];
static uint32_t usb_last_send_size;

static int bytes_are(const uint8_t *memory, size_t length, uint8_t value)
{
    for (size_t i = 0; i < length; ++i)
        if (memory[i] != value) return 0;
    return 1;
}

static int words_are_zero(const uint8_t *memory, size_t length)
{
    return bytes_are(memory, length, 0U);
}

static void setup_case(enum phase initial_phase, enum eye_session_state state)
{
    memset(&session, 0, sizeof session);
    memset((void *)&g6_secure_cleanup_diag, 0, sizeof g6_secure_cleanup_diag);
    memset(hello, 0x71, sizeof hello);
    memset(ack, 0x72, sizeof ack);
    memset(private_key, 0x53, sizeof private_key);
    memset(random_seed, 0x64, sizeof random_seed);
    memset(session.pinned_pk_hash, 0x11, sizeof session.pinned_pk_hash);
    memset(session.last_transcript, 0x22, sizeof session.last_transcript);
    memset(session.transcript_hash, 0x33, sizeof session.transcript_hash);
    memset(session.video_key, 0x44, sizeof session.video_key);
    memset(session.control_key, 0x55, sizeof session.control_key);
    session.state = (uint8_t)state;
    session.host_finished_verified = state == EYE_STATE_STREAMING;
    session.board_finished_sent = state == EYE_STATE_CONFIRM;
    phase = initial_phase;

    gcm_clear_calls = 0U;
    cleanup_diag_flush_calls = 0U;
    memset(cleanup_calls, 0, sizeof cleanup_calls);
    memset(cleanup_order, 0, sizeof cleanup_order);
    cleanup_order_count = 0U;
    cleanup_fail_at = 0U;
    fake_usb_ready = 1;
    fake_connection_epoch = 7U;
    usb_send_calls = 0U;
    memset(usb_last_send, 0, sizeof usb_last_send);
    usb_last_send_size = 0U;
#ifdef G6_SECURE_CLEANUP
    diag_hello_attempt_count = 0U;
    diag_hello_ack_send_attempts = 0U;
    diag_hello_ack_send_status = UINT32_MAX;
#endif
    g6_status = 10U;
    g6_fatal_errors = 20U;
    g6_control_errors = 30U;
    g6_disconnects = 40U;
    g6_transport_errors = 0U;
#ifdef G6_SECURE_CLEANUP
    memset((void *)&g6_transport_failure_diag, 0,
           sizeof g6_transport_failure_diag);
#endif
}

static int long_term_material_preserved(void)
{
    return bytes_are(private_key, sizeof private_key, 0x53) &&
           bytes_are(random_seed, sizeof random_seed, 0x64);
}

static int session_closed(enum eye_session_state expected_state)
{
    return session.state == expected_state &&
           bytes_are(session.pinned_pk_hash, sizeof session.pinned_pk_hash, 0x11) &&
           bytes_are(session.last_transcript, sizeof session.last_transcript, 0x33) &&
           words_are_zero(session.transcript_hash, sizeof session.transcript_hash) &&
           words_are_zero(session.video_key, sizeof session.video_key) &&
           words_are_zero(session.control_key, sizeof session.control_key);
}

static int cleanup_result(unsigned stage)
{
    cleanup_calls[stage - 1U]++;
    cleanup_order[cleanup_order_count++] = stage;
    if (cleanup_fail_at == stage) return (int)(40U + stage);
    return 0;
}

void g3_usb_zeroize(void)
{
    ++gcm_clear_calls;
}

int g3_usb_cleanup_stop_dma_and_clear_gcm(void)
{
    int status = cleanup_result(1U);
    if (!status) ++gcm_clear_calls;
    return status;
}

int g3_usb_cleanup_wipe_frame_and_sealed(void)
{
    return cleanup_result(2U);
}

int usb_cdc_secure_cleanup_tx(uint8_t *buffer, unsigned capacity)
{
    if (buffer != tx || capacity != sizeof tx) return 99;
    return cleanup_result(3U);
}

int usb_cdc_send(uint8_t *data, uint32_t size)
{
    if (size > sizeof usb_last_send) return 98;
    ++usb_send_calls;
    usb_last_send_size = size;
    memcpy(usb_last_send, data, size);
    return 0;
}

int usb_cdc_take_control(uint8_t *out, uint32_t capacity)
{
    (void)out;
    (void)capacity;
    return 0;
}

int usb_cdc_init(void)
{
    return 0;
}

int g3_usb_init(unsigned camera_cfg)
{
    (void)camera_cfg;
    return 0;
}

int g3_usb_capture(const uint8_t **data, unsigned *size)
{
    (void)data;
    (void)size;
    return 1;
}

int g3_usb_resume(void)
{
    return 0;
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

int g6_candidate_recover_camera(void)
{
    return 1;
}

int xil_printf(const char *format, ...)
{
    (void)format;
    return 0;
}

int eye_mlkem_check_sk(const uint8_t sk[1632])
{
    (void)sk;
    return 0;
}

int g3_usb_flush(void)
{
    return 0;
}

int usb_cdc_ready(void)
{
    return fake_usb_ready;
}

uint32_t usb_cdc_connection_epoch(void)
{
    return fake_connection_epoch;
}

int eye_mlkem_dec(uint8_t ss[32], const uint8_t ct[768], const uint8_t sk[1632])
{
    (void)ss;
    (void)ct;
    (void)sk;
    return -1;
}

static void put_be64(uint8_t *out, uint64_t value)
{
    for (unsigned i = 0; i < 8U; ++i)
        out[i] = (uint8_t)(value >> (56U - 8U * i));
}

static int make_command(uint8_t type, uint8_t message[52])
{
    static const uint8_t label[] = "host command";
    uint8_t body[40] = {0}, context[sizeof label - 1U + 32U + 20U];
    uint8_t tag[32];
    put_be64(body, 0U);
    if (eye_control_encode(message, 52U, type, body, sizeof body)) return 1;
    memcpy(context, label, sizeof label - 1U);
    memcpy(context + sizeof label - 1U, session.transcript_hash, 32U);
    memcpy(context + sizeof label - 1U + 32U, message, 20U);
    if (eye_hmac_sha256(tag, session.control_key, sizeof session.control_key,
                        context, sizeof context)) return 2;
    memcpy(body + 8U, tag, sizeof tag);
    memset(tag, 0, sizeof tag);
    memset(context, 0, sizeof context);
    return eye_control_encode(message, 52U, type, body, sizeof body);
}

static int make_bad_finished(uint8_t message[44])
{
    uint8_t body[32];
    memset(body, 0xa5, sizeof body);
    return eye_control_encode(message, 44U, EYE_FINISHED_HOST, body, sizeof body);
}

static int test_duplicate_hello_replays_cached_ack(void)
{
    uint8_t hello_message[48], body[36] = {1U, 1U, 0U, 1U};
    uint8_t first_reply[sizeof usb_last_send];
    for (unsigned i = 0; i < 32U; ++i) body[4U + i] = (uint8_t)(i + 1U);
    setup_case(WAIT_HELLO, EYE_STATE_IDLE);
    if (eye_control_encode(hello_message, sizeof hello_message,
                           EYE_HELLO, body, sizeof body)) return 1;
    if (handle_control(hello_message, sizeof hello_message) ||
        phase != WAIT_KEM || usb_send_calls != 1U || usb_last_send_size != 51U)
        return 2;
    memcpy(first_reply, usb_last_send, usb_last_send_size);
    if (handle_control(hello_message, sizeof hello_message) ||
        phase != WAIT_KEM || usb_send_calls != 2U ||
        usb_last_send_size != 51U ||
        memcmp(first_reply, usb_last_send, usb_last_send_size) != 0 ||
        g6_control_errors != 30U ||
        g6_fatal_errors != 20U || g6_status != 10U)
        return 3;
#ifdef G6_SECURE_CLEANUP
    if (diag_hello_attempt_count != 2U || diag_hello_ack_send_attempts != 2U ||
        diag_hello_ack_send_status != 0U) return 4;
#endif
    body[35] ^= 1U;
    if (eye_control_encode(hello_message, sizeof hello_message,
                           EYE_HELLO, body, sizeof body) ||
        handle_control(hello_message, sizeof hello_message) == 0 ||
        phase != WAIT_KEM || usb_send_calls != 2U)
        return 5;
    return 0;
}

#ifdef G6_SECURE_CLEANUP
static int callbacks_stopped_at(unsigned fail_stage)
{
    for (unsigned i = 0; i < 3U; ++i) {
        unsigned expected = i < fail_stage ? 1U : 0U;
        if (cleanup_calls[i] != expected) return 0;
    }
    if (cleanup_order_count != fail_stage) return 0;
    for (unsigned i = 0; i < fail_stage; ++i)
        if (cleanup_order[i] != i + 1U) return 0;
    return 1;
}

static int cleanup_failed_diag(unsigned stage)
{
    return g6_secure_cleanup_diag.stage == G6_CLEANUP_FAILED &&
           g6_secure_cleanup_diag.failed_stage == stage &&
           g6_secure_cleanup_diag.result == 40U + stage;
}
#endif

static int test_fail_closed(void)
{
    setup_case(STREAM, EYE_STATE_STREAMING);
#ifdef G6_SECURE_CLEANUP
    for (unsigned fail = 1U; fail <= 3U; ++fail) {
        setup_case(STREAM, EYE_STATE_STREAMING);
        cleanup_fail_at = fail;
        fail_closed();
        if (phase != FAULT || g6_fatal_errors != 21U || g6_status != 11U ||
            !callbacks_stopped_at(fail) || !cleanup_failed_diag(fail) ||
            cleanup_diag_flush_calls != 1U ||
            !session_closed(EYE_STATE_ERROR) || !long_term_material_preserved())
            return (int)(10U + fail);
    }
#else
    fail_closed();
    if (phase != FAULT || g6_fatal_errors != 21U || g6_status != 11U ||
        gcm_clear_calls != 1U || cleanup_order_count != 0U ||
        cleanup_diag_flush_calls != 0U ||
        !session_closed(EYE_STATE_ERROR) || !long_term_material_preserved())
        return 1;
#endif
    return 0;
}

static int test_disconnect(void)
{
    setup_case(STREAM, EYE_STATE_STREAMING);
#ifdef G6_SECURE_CLEANUP
    if (retire_disconnected_session(4U, 0U, 0U, 14U) != 0) return 1;
    if (phase != WAIT_HELLO || g6_disconnects != 41U ||
        g6_transport_errors != 0U ||
        g6_transport_failure_diag.send_status != 4U ||
        g6_transport_failure_diag.resume_status != 0U ||
        g6_transport_failure_diag.usb_ready != 0U ||
        g6_transport_failure_diag.connection_epoch != 14U ||
        g6_transport_failure_diag.transport_error_count != 0U ||
        !callbacks_stopped_at(3U) || g6_secure_cleanup_diag.stage != G6_CLEANUP_COMPLETE ||
        g6_secure_cleanup_diag.result != 0U || gcm_clear_calls != 1U ||
        cleanup_diag_flush_calls != 1U ||
        !session_closed(EYE_STATE_ERROR) || !long_term_material_preserved())
        return 2;
    for (unsigned fail = 1U; fail <= 3U; ++fail) {
        setup_case(STREAM, EYE_STATE_STREAMING);
        cleanup_fail_at = fail;
        if (retire_disconnected_session(4U, 0U, 0U, 14U) != 1 ||
            phase != FAULT || g6_disconnects != 40U ||
            g6_fatal_errors != 21U || g6_status != 11U ||
            g6_transport_errors != 1U ||
            g6_transport_failure_diag.send_status != 4U ||
            g6_transport_failure_diag.resume_status != 0U ||
            g6_transport_failure_diag.usb_ready != 0U ||
            g6_transport_failure_diag.connection_epoch != 14U ||
            g6_transport_failure_diag.transport_error_count != 1U ||
            !callbacks_stopped_at(fail) || !cleanup_failed_diag(fail) ||
            cleanup_diag_flush_calls != 1U ||
            !session_closed(EYE_STATE_ERROR) || !long_term_material_preserved())
            return (int)(10U + fail);
    }
    setup_case(STREAM, EYE_STATE_STREAMING);
    if (retire_disconnected_session(UINT32_MAX, 0U, 0U, 15U) != 0 ||
        g6_transport_failure_diag.send_status != UINT32_MAX ||
        g6_transport_failure_diag.usb_ready != 0U ||
        g6_transport_failure_diag.connection_epoch != 15U ||
        g6_transport_failure_diag.transport_error_count != 0U ||
        g6_transport_errors != 0U || g6_disconnects != 41U)
        return 20;
#else
    if (retire_disconnected_session(UINT32_MAX, 0U, 0U, 7U) != 0) return 1;
    if (phase != WAIT_HELLO || g6_disconnects != 41U || g6_fatal_errors != 20U ||
        gcm_clear_calls != 1U || cleanup_order_count != 0U ||
        cleanup_diag_flush_calls != 0U ||
        !session_closed(EYE_STATE_ERROR) || !long_term_material_preserved())
        return 1;
#endif
    return 0;
}

static int exercise_stop_or_rekey(uint8_t command_type, unsigned fail_stage)
{
    uint8_t message[52];
    enum eye_session_state expected = command_type == EYE_STOP ?
        EYE_STATE_IDLE : EYE_STATE_REKEY;
    setup_case(STREAM, EYE_STATE_STREAMING);
    cleanup_fail_at = fail_stage;
    if (make_command(command_type, message)) return 1;
    if (handle_control(message, sizeof message)) return 2;
#ifdef G6_SECURE_CLEANUP
    if (fail_stage) {
        if (phase != FAULT || g6_fatal_errors != 21U || g6_status != 11U ||
            !callbacks_stopped_at(fail_stage) || !cleanup_failed_diag(fail_stage) ||
            cleanup_diag_flush_calls != 1U ||
            !session_closed(EYE_STATE_ERROR) || !long_term_material_preserved())
            return 3;
    } else if (phase != WAIT_HELLO || !callbacks_stopped_at(3U) ||
               g6_secure_cleanup_diag.stage != G6_CLEANUP_COMPLETE ||
               g6_secure_cleanup_diag.result != 0U || gcm_clear_calls != 1U ||
               cleanup_diag_flush_calls != 1U ||
               !session_closed(expected) || !long_term_material_preserved()) {
        return 4;
    }
#else
    if (fail_stage || phase != WAIT_HELLO || gcm_clear_calls != 1U ||
        cleanup_order_count != 0U || cleanup_diag_flush_calls != 0U ||
        !session_closed(expected) ||
        !long_term_material_preserved()) return 5;
#endif
    return 0;
}

static int test_stop_and_rekey(void)
{
    const uint8_t commands[] = {EYE_STOP, EYE_REKEY};
    for (unsigned i = 0; i < sizeof commands; ++i) {
        if (exercise_stop_or_rekey(commands[i], 0U)) return (int)(10U + i);
#ifdef G6_SECURE_CLEANUP
        for (unsigned fail = 1U; fail <= 3U; ++fail)
            if (exercise_stop_or_rekey(commands[i], fail))
                return (int)(20U + i * 4U + fail);
#endif
    }
    return 0;
}

static int exercise_auth_failure(unsigned fail_stage)
{
    uint8_t message[44];
    setup_case(WAIT_FINISHED, EYE_STATE_CONFIRM);
    cleanup_fail_at = fail_stage;
    if (make_bad_finished(message)) return 1;
    if (handle_control(message, sizeof message) == 0) return 2;
    /* Mirrors the connected/non-disconnect error branch around handle_control. */
    if (!usb_cdc_ready() || usb_cdc_connection_epoch() != fake_connection_epoch) {
        (void)retire_disconnected_session(UINT32_MAX, 0U,
            (unsigned)usb_cdc_ready(), usb_cdc_connection_epoch());
    } else {
        ++g6_control_errors;
        fail_closed();
    }
    if (phase != FAULT || g6_control_errors != 31U || g6_fatal_errors != 21U ||
        g6_status != 11U || !session_closed(EYE_STATE_ERROR) ||
        !long_term_material_preserved()) return 3;
#ifdef G6_SECURE_CLEANUP
    if (!callbacks_stopped_at(fail_stage ? fail_stage : 3U) ||
        (fail_stage && !cleanup_failed_diag(fail_stage)) ||
        (!fail_stage && (g6_secure_cleanup_diag.stage != G6_CLEANUP_COMPLETE ||
                         g6_secure_cleanup_diag.result != 0U || gcm_clear_calls != 1U ||
                         cleanup_diag_flush_calls != 1U)) ||
        (fail_stage && cleanup_diag_flush_calls != 1U))
        return 4;
#else
    if (fail_stage || gcm_clear_calls != 1U || cleanup_order_count != 0U ||
        cleanup_diag_flush_calls != 0U) return 5;
#endif
    return 0;
}

static int test_authentication_failure(void)
{
#ifdef G6_SECURE_CLEANUP
    if (exercise_auth_failure(0U)) return 1;
    for (unsigned fail = 1U; fail <= 3U; ++fail)
        if (exercise_auth_failure(fail)) return (int)(10U + fail);
#else
    if (exercise_auth_failure(0U)) return 1;
#endif
    return 0;
}

int main(void)
{
    int duplicate_hello_status = test_duplicate_hello_replays_cached_ack();
    int fail_closed_status = test_fail_closed();
    int disconnect_status = test_disconnect();
    int command_status = test_stop_and_rekey();
    int auth_status = test_authentication_failure();
    if (duplicate_hello_status || fail_closed_status || disconnect_status || command_status || auth_status) {
        fprintf(stderr, "g6_cleanup_paths_failed=%d,%d,%d,%d,%d\n",
                duplicate_hello_status,
                fail_closed_status, disconnect_status, command_status, auth_status);
        return 1;
    }
#ifdef G6_SECURE_CLEANUP
    puts("candidate_cleanup_paths=PASS cleanup_failure_stops=PASS session_semantics=PASS");
#else
    puts("default_gcm_clear_paths=PASS session_semantics=PASS");
#endif
    return 0;
}
