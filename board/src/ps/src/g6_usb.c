/* G6 development profile uses JTAG provisioning; G6_PRODUCTION requires an
 * explicitly linked platform security provider and excludes that mailbox. */
#include "xil_printf.h"
#ifdef SDT
#include "xiltimer.h"
#else
#include "xtime_l.h"
#endif
#ifdef G6_SECURE_CLEANUP
#include "xil_cache.h"
#endif
#include "session.h"
#include "ephemeral.h"
#include "protocol.h"
#include "g6_control_dispatch.h"
#include "g6_secure_cleanup.h"
#ifdef G6_AUTO_RECOVERY
#include "g6_auto_recovery.h"
#include "g6_rekey_diag.h"
#endif
#ifndef G6_PRODUCTION
#define MLK_CONFIG_PARAMETER_SET 512
#define MLK_CONFIG_NAMESPACE_PREFIX eye_mlkem
#define MLK_CONFIG_NO_RANDOMIZED_API
#define MLK_CONFIG_NO_SUPERCOP
#define MLK_CONFIG_NO_KEYPAIR_API
#define MLK_CONFIG_NO_ENCAPS_API
#include "mlkem/mlkem_native.h"
#endif
#include <stdint.h>
#include <string.h>
#ifdef G6_DEV_USB_BOOTSTRAP
#if defined(G6_PRODUCTION) || !defined(G6_SECURE_CLEANUP)
#error "Development USB bootstrap requires cleanup and excludes production"
#endif
#include "g6_dev_bootstrap.h"
#include "xil_io.h"
int usb_cdc_bootstrap_rx_pending(void);
int usb_cdc_bootstrap_rx_interrupted(void);
void usb_cdc_bootstrap_rx_clear(void);
static struct eye_bootstrap usb_bootstrap;
static uint64_t bootstrap_wire_started;
static uint32_t bootstrap_irq_saved;
static int bootstrap_irq_held;
static uint32_t bootstrap_irq_disable(void) {
    uint32_t saved = 0;
#if defined(__arm__)
    __asm__ volatile("mrs %0, cpsr\n\tcpsid i" : "=r"(saved) :: "memory", "cc");
#endif
    return saved;
}
static void bootstrap_irq_release(void) {
    if (!bootstrap_irq_held) return;
#if defined(__arm__)
    if (!(bootstrap_irq_saved & 0x80U)) __asm__ volatile("cpsie i" ::: "memory", "cc");
#else
    (void)bootstrap_irq_saved;
#endif
    bootstrap_irq_held = 0;
}
#endif
#ifdef G6_PRODUCTION
#include "g6_production_provider.h"
#include "g6_hmac_drbg.h"
#endif

#define PROVISION_MAGIC 0x36475345U
#define CAMERA_CFG ((1U << 25) | (1000U << 9) | (12U << 3) | 4U | 2U)

int g3_usb_init(unsigned camera_cfg);
int g3_usb_capture(const uint8_t **data, unsigned *size);
int g3_usb_flush(void);
int g3_usb_resume(void);
void g3_usb_zeroize(void);
#ifdef G6_SECURE_CLEANUP
int g3_usb_cleanup_stop_dma_and_clear_gcm(void);
int g3_usb_cleanup_wipe_frame_and_sealed(void);
#endif
#ifdef G6_AUTO_RECOVERY
int g6_candidate_recover_camera(void);
#endif
int g3_usb_encrypt(const uint8_t *plain, unsigned size, const uint8_t aad[40],
                   const uint8_t key[16], uint32_t epoch, uint64_t sequence,
                   const uint8_t **sealed);
int usb_cdc_init(void);
int usb_cdc_ready(void);
uint32_t usb_cdc_connection_epoch(void);
int usb_cdc_send(uint8_t *data, uint32_t size);
#ifdef G6_SECURE_CLEANUP
int usb_cdc_secure_cleanup_tx(uint8_t *buffer, unsigned capacity);
#endif
int usb_cdc_take_control(uint8_t *out, uint32_t capacity);

#if !defined(G6_PRODUCTION) && !defined(G6_DEV_USB_BOOTSTRAP)
volatile uint8_t g6_sk_load[1632] __attribute__((aligned(64)));
volatile uint8_t g6_seed_load[32] __attribute__((aligned(64)));
volatile uint32_t g6_ready __attribute__((aligned(64)));
#endif
volatile uint32_t g6_status __attribute__((aligned(64)));
volatile uint32_t g6_frames __attribute__((aligned(64)));
volatile uint32_t g6_dropped __attribute__((aligned(64)));
volatile uint32_t g6_control_errors __attribute__((aligned(64)));
volatile uint32_t g6_capture_errors __attribute__((aligned(64)));
volatile uint32_t g6_transport_errors __attribute__((aligned(64)));
volatile uint32_t g6_fatal_errors __attribute__((aligned(64)));
volatile uint32_t g6_disconnects __attribute__((aligned(64)));
volatile uint32_t g6_fault_inject __attribute__((aligned(64)));
volatile uint32_t g6_injected_capture_errors __attribute__((aligned(64)));
#ifdef G6_AUTO_RECOVERY
volatile uint32_t g6_auto_recovery_request __attribute__((aligned(64)));
volatile struct g6_transport_failure_diag g6_transport_failure_diag
    __attribute__((aligned(64)));
#endif

#ifndef G6_PRODUCTION
static uint8_t private_key[1632], random_seed[32];
#else
static struct eye_hmac_drbg production_drbg;
#endif
static uint8_t hello[48], ack[48], tx[G6_SECURE_TX_CAPACITY] __attribute__((aligned(64)));
_Static_assert(sizeof tx == 1472U && (sizeof tx & 63U) == 0U &&
               sizeof tx >= 43U + 1400U + 16U,
               "G6 TX buffer cleanup capacity");
static struct eye_session session;
static struct eye_ephemeral ephemeral;
static uint8_t negotiated_suite, business_ready;
static XTime profile_started;
#ifndef G6_PRODUCTION
static uint64_t random_counter;
#endif
static uint32_t frame_id;

enum phase { WAIT_HELLO, WAIT_KEM, WAIT_FINISHED, WAIT_START, STREAM, FAULT, WAIT_EPHEMERAL };
static enum phase phase;

#ifdef G6_AUTO_RECOVERY
volatile struct g6_rekey_diag g6_rekey_diagnostic __attribute__((aligned(64))) = {
    .magic = G6_REKEY_DIAG_MAGIC,
    .version = G6_REKEY_DIAG_VERSION,
    .size_bytes = sizeof(struct g6_rekey_diag),
    .hello_ack_send_status = UINT32_MAX,
    .cleanup_last_result = UINT32_MAX
};
static uint32_t diag_last_control_type;
static uint32_t diag_received_control_count;
static uint32_t diag_hello_attempt_count;
static uint32_t diag_hello_ack_send_attempts;
static uint32_t diag_hello_ack_send_status = UINT32_MAX;
static uint32_t diag_cleanup_count;
static uint32_t diag_cleanup_last_result = UINT32_MAX;

static void diag_memory_barrier(void) {
#if defined(__arm__)
    __asm__ volatile("dmb sy" ::: "memory");
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
}

static void publish_rekey_diag(void) {
    uint32_t sequence = g6_rekey_diagnostic.sequence;
    if (sequence & 1U) ++sequence;
    ++sequence;
    g6_rekey_diagnostic.sequence = sequence;
    diag_memory_barrier();
    Xil_DCacheFlushRange((uintptr_t)&g6_rekey_diagnostic, 64U);
#if defined(__arm__)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
    g6_rekey_diagnostic.phase = (uint32_t)phase;
    g6_rekey_diagnostic.last_control_type = diag_last_control_type;
    g6_rekey_diagnostic.received_control_count = diag_received_control_count;
    g6_rekey_diagnostic.hello_attempt_count = diag_hello_attempt_count;
    g6_rekey_diagnostic.hello_ack_send_attempts = diag_hello_ack_send_attempts;
    g6_rekey_diagnostic.hello_ack_send_status = diag_hello_ack_send_status;
    g6_rekey_diagnostic.cleanup_count = diag_cleanup_count;
    g6_rekey_diagnostic.cleanup_last_result = diag_cleanup_last_result;
    g6_rekey_diagnostic.control_errors = g6_control_errors;
    g6_rekey_diagnostic.fatal_errors = g6_fatal_errors;
    g6_rekey_diagnostic.transport_errors = g6_transport_errors;
    usb_cdc_g6_diag_fill(&g6_rekey_diagnostic);
    diag_memory_barrier();
    g6_rekey_diagnostic.sequence_end = sequence + 1U;
    g6_rekey_diagnostic.sequence = sequence + 1U;
    diag_memory_barrier();
    Xil_DCacheFlushRange((uintptr_t)&g6_rekey_diagnostic,
                         sizeof(g6_rekey_diagnostic));
#if defined(__arm__)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __atomic_thread_fence(__ATOMIC_SEQ_CST);
#endif
}
#endif

static void wipe(void *p, unsigned length) {
    eye_g6_control_wipe(p, length);
}
static void clear_handshake_cache(void) {
    wipe(hello, sizeof hello);
    wipe(ack, sizeof ack);
    eye_ephemeral_wipe(&ephemeral);
}
#ifdef G6_SECURE_CLEANUP
static int cleanup_stop_dma_and_gcm(void *context) {
    (void)context;
    return g3_usb_cleanup_stop_dma_and_clear_gcm();
}
static int cleanup_wipe_frame_and_sealed(void *context) {
    (void)context;
    return g3_usb_cleanup_wipe_frame_and_sealed();
}
static int cleanup_usb_tx(void *context) {
    (void)context;
    return usb_cdc_secure_cleanup_tx(tx, sizeof tx);
}
static const struct g6_secure_cleanup_ops cleanup_ops = {
    cleanup_stop_dma_and_gcm,
    cleanup_wipe_frame_and_sealed,
    cleanup_usb_tx
};
static int secure_cleanup(void) {
#ifdef G6_AUTO_RECOVERY
    ++diag_cleanup_count;
    diag_cleanup_last_result = UINT32_MAX;
    publish_rekey_diag();
#endif
    int status = g6_secure_cleanup_run(NULL, &cleanup_ops, &g6_secure_cleanup_diag);
#ifdef G6_AUTO_RECOVERY
    diag_cleanup_last_result = (uint32_t)status;
#endif
    Xil_DCacheFlushRange((UINTPTR)&g6_secure_cleanup_diag,
                         sizeof g6_secure_cleanup_diag);
#if defined(__arm__)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
#ifdef G6_AUTO_RECOVERY
    publish_rekey_diag();
#endif
    return status;
}
#endif
static void be16(uint8_t *p, unsigned n) { p[0] = n >> 8; p[1] = n; }
#ifndef G6_PRODUCTION
static void be64(uint8_t *p, uint64_t n) {
    for (unsigned i = 0; i < 8; ++i) p[i] = n >> (56 - 8*i);
}
#endif
static int send_control(const uint8_t *message, unsigned length) {
    if (length < 12 || length > 1036) return 1;
    tx[0] = 1; be16(tx + 1, length);
    memcpy(tx + 3, message, length);
    return usb_cdc_send(tx, length + 3);
}
static int board_random(uint8_t out[32], const uint8_t host_random[32]) {
#ifdef G6_PRODUCTION
    int status;
    wipe(out, 32U);
    if (eye_hmac_drbg_needs_reseed(&production_drbg)) {
        uint8_t entropy[48] = {0};
        status = g6_production_entropy_bytes(entropy, sizeof entropy);
        if (!status)
            status = eye_hmac_drbg_reseed(&production_drbg, entropy, 32U,
                                          entropy + 32U, 16U);
        wipe(entropy, sizeof entropy);
        if (status) eye_hmac_drbg_uninstantiate(&production_drbg);
    } else {
        status = EYE_HMAC_DRBG_OK;
    }
    if (!status)
        status = eye_hmac_drbg_generate(&production_drbg, out, 32U,
                                        host_random, 32U);
    if (status) wipe(out, 32U);
    return status;
#else
    uint8_t input[40];
    if (random_counter == UINT64_MAX) { wipe(out, 32); return 1; }
    memcpy(input, host_random, 32);
    be64(input + 32, random_counter++);
    int status = eye_hmac_sha256(out, random_seed, sizeof random_seed, input, sizeof input);
    wipe(input, sizeof input);
    return status;
#endif
}
static int ephemeral_coins(uint8_t out[64]) {
#ifdef G6_PRODUCTION
    int status = g6_production_entropy_bytes(out, 64U);
#else
    /* Development seed is PC-known: this profile makes no forward-secrecy claim. */
    int status = board_random(out, session.transcript_hash);
    if (!status) status = board_random(out + 32, session.transcript_hash);
#endif
    if (status) wipe(out, 64U);
    return status;
}
#ifdef G6_PRODUCTION
static int initialize_production_security(void) {
    uint8_t public_key[800] = {0}, entropy[48] = {0};
    eye_hmac_drbg_uninstantiate(&production_drbg);
    int status = g6_production_security_init();
    if (!status) status = g6_production_entropy_bytes(entropy, sizeof entropy);
    if (!status)
        status = eye_hmac_drbg_instantiate(&production_drbg, 256U, entropy, 32U,
                                           entropy + 32U, 16U, NULL, 0U);
    if (!status) status = g6_production_read_mlkem512_public_key(public_key);
    if (!status) status = eye_session_init(&session, public_key);
    wipe(public_key, sizeof public_key);
    wipe(entropy, sizeof entropy);
    if (status) {
        eye_hmac_drbg_uninstantiate(&production_drbg);
        g6_production_security_shutdown();
    }
    return status;
}

static int production_decapsulate(uint8_t shared[32], const uint8_t ciphertext[768]) {
    wipe(shared, 32U);
    int status = g6_production_mlkem512_decapsulate(
        shared, ciphertext, session.pinned_pk_hash);
    if (status) wipe(shared, 32U);
    return status;
}

/* No application control/TX transfer has been submitted before transport
 * startup succeeds, so tx is still CPU-owned on these startup error paths. */
static void production_startup_wipe_state(void) {
    eye_session_reset(&session);
    clear_handshake_cache();
    wipe(tx, sizeof tx);
    phase = FAULT;
    eye_hmac_drbg_uninstantiate(&production_drbg);
}

static void production_startup_teardown(void) {
    production_startup_wipe_state();
    g6_production_security_shutdown();
}

static int initialize_production_transports(void) {
    int status = g3_usb_init(CAMERA_CFG);
    if (!status) status = usb_cdc_init();
    if (status) production_startup_teardown();
    return status;
}

static int initialize_production_startup(void) {
    int status = initialize_production_security();
    if (status) {
        /* The security initializer already shut down a partial provider init. */
        production_startup_wipe_state();
        return status;
    }
    return initialize_production_transports();
}
#endif
static void mark_fault(void) {
    eye_session_error(&session);
    clear_handshake_cache();
#ifndef G6_PRODUCTION
    /* A terminal development fault cannot resume with the loaded test key. */
    wipe(private_key, sizeof private_key);
    wipe(random_seed, sizeof random_seed);
    random_counter = 0U;
#ifndef G6_DEV_USB_BOOTSTRAP
    wipe((void *)g6_sk_load, sizeof g6_sk_load);
    wipe((void *)g6_seed_load, sizeof g6_seed_load);
    g6_ready = 0U;
#else
    eye_boot_fault(&usb_bootstrap);
    usb_cdc_bootstrap_rx_clear();
#endif
#endif
#ifdef G6_PRODUCTION
    eye_hmac_drbg_uninstantiate(&production_drbg);
    g6_production_security_shutdown();
#endif
    phase = FAULT;
    ++g6_fatal_errors;
    ++g6_status;
#ifdef G6_AUTO_RECOVERY
    publish_rekey_diag();
#endif
}
static void fail_closed(void) {
#ifdef G6_SECURE_CLEANUP
    (void)secure_cleanup();
#else
    g3_usb_zeroize();
#endif
    mark_fault();
}
#ifdef G6_DEV_USB_BOOTSTRAP
static uint64_t bootstrap_now_ms(void) {
    XTime now;
    XTime_GetTime(&now);
    return now / (COUNTS_PER_SECOND / 1000U);
}
static int bootstrap_activate(const uint8_t pin[32], const uint8_t sk[1632],
                               const uint8_t seed[32]) {
    uint8_t computed[32] = {0};
    unsigned different = 0U;
    int status = eye_mlkem_check_sk(sk);
    if (!status) status = eye_sha256(computed, sk + 768U, 800U);
    for (unsigned i = 0; i < 32U; ++i) different |= computed[i] ^ pin[i];
    if (!status && different) status = 1;
    if (!status) status = eye_session_init(&session, sk + 768U);
    if (!status) {
        /* Commit identity + READY as one ISR-atomic transition. Crypto checks
         * run with IRQs enabled, then recheck the original receiving epoch. */
        bootstrap_irq_saved = bootstrap_irq_disable();
        bootstrap_irq_held = 1;
        if (!usb_cdc_ready() || usb_cdc_connection_epoch() != usb_bootstrap.epoch ||
                bootstrap_now_ms() - usb_bootstrap.started_ms >= 10000U)
            status = 1;
    }
    if (!status) {
        memcpy(private_key, sk, sizeof private_key);
        memcpy(random_seed, seed, sizeof random_seed);
        random_counter = 0U;
    }
    wipe(computed, sizeof computed);
    return status;
}
static int retire_disconnected_session(unsigned send_status, unsigned resume_status,
                                       unsigned ready_at_failure, uint32_t epoch_at_failure);
static int bootstrap_control(const uint8_t *message, unsigned length) {
    enum eye_boot_state previous = usb_bootstrap.state;
    int status = eye_boot_process(&usb_bootstrap, message, length, bootstrap_now_ms(),
                                  usb_cdc_connection_epoch(), bootstrap_activate);
    bootstrap_irq_release();
    if (status) fail_closed();
    uint8_t reply[EYE_BOOT_ACK];
    eye_boot_reply(&usb_bootstrap, reply);
    uint32_t epoch_before_send = usb_cdc_connection_epoch();
    int sent = send_control(reply, sizeof reply);
    wipe(reply, sizeof reply);
    if (sent) {
        unsigned ready = (unsigned)usb_cdc_ready();
        uint32_t epoch = usb_cdc_connection_epoch();
        /* The host can consume READY and close before the DMA completion check. */
        if (!status && usb_bootstrap.state == EYE_BOOT_READY && sent == 1 &&
                (!ready || epoch != epoch_before_send)) {
            if (retire_disconnected_session((unsigned)sent, 0U, ready, epoch)) return 1;
        } else {
            fail_closed(); return 1;
        }
    }
    if (previous != EYE_BOOT_READY && usb_bootstrap.state == EYE_BOOT_READY) {
        g6_status = 1U;
        xil_printf("G6_DEV_USB_READY boot_mode=0x%02x\r\n", Xil_In32(0xf800025cU) & 15U);
    }
    return status;
}
#endif
static int retire_disconnected_session(unsigned send_status,
                                       unsigned resume_status,
                                       unsigned ready_at_failure,
                                       uint32_t epoch_at_failure) {
    /* Fatal faults retire the provider or wipe development identity/seed. */
    if (phase == FAULT) return 1;
#ifndef G6_AUTO_RECOVERY
    (void)send_status;
    (void)resume_status;
    (void)ready_at_failure;
    (void)epoch_at_failure;
#endif
#ifdef G6_AUTO_RECOVERY
    g6_transport_failure_diag.send_status = send_status;
    g6_transport_failure_diag.resume_status = resume_status;
    g6_transport_failure_diag.phase = (uint32_t)phase;
    g6_transport_failure_diag.usb_ready = ready_at_failure;
    g6_transport_failure_diag.connection_epoch = epoch_at_failure;
#endif
#ifdef G6_SECURE_CLEANUP
    if (secure_cleanup()) {
#ifdef G6_AUTO_RECOVERY
        g6_transport_failure_diag.transport_error_count = g6_transport_errors + 1U;
#endif
        ++g6_transport_errors;
        mark_fault();
        return 1;
    } else {
        eye_session_error(&session);
        clear_handshake_cache();
        phase = WAIT_HELLO;
    }
#else
    g3_usb_zeroize();
    eye_session_error(&session);
    clear_handshake_cache();
    phase = WAIT_HELLO;
#endif
    ++g6_disconnects;
#ifdef G6_AUTO_RECOVERY
    g6_transport_failure_diag.transport_error_count = g6_transport_errors;
    publish_rekey_diag();
#endif
    return 0;
}
static int handle_frame_send_failure(unsigned send_status, unsigned resume_status,
                                     uint32_t epoch_before) {
    unsigned ready_at_failure = (unsigned)usb_cdc_ready();
    uint32_t epoch_at_failure = usb_cdc_connection_epoch();
    /* DTR/epoch evidence, not a send error alone, permits a fresh session. */
    if (g6_secure_expected_usb_disconnect(send_status, resume_status,
            ready_at_failure, epoch_before, epoch_at_failure))
        return retire_disconnected_session(send_status, resume_status,
                                            ready_at_failure, epoch_at_failure);
#ifdef G6_AUTO_RECOVERY
    g6_transport_failure_diag.send_status = send_status;
    g6_transport_failure_diag.resume_status = resume_status;
    g6_transport_failure_diag.phase = (uint32_t)phase;
    g6_transport_failure_diag.usb_ready = ready_at_failure;
    g6_transport_failure_diag.connection_epoch = epoch_at_failure;
    g6_transport_failure_diag.transport_error_count = g6_transport_errors + 1U;
#endif
    ++g6_transport_errors;
    fail_closed();
    return 1;
}
static int handle_control(const uint8_t *message, unsigned length) {
    uint8_t type, body_ack[36] = {1, 1, 0, 1};
    const uint8_t *body;
    uint32_t body_length;
    if (eye_control_decode(&type, &body, &body_length, message, length)) return 1;
#ifdef G6_AUTO_RECOVERY
    diag_last_control_type = type;
#endif
    if (phase == WAIT_HELLO && type == EYE_HELLO && length == 48) {
        negotiated_suite = body[3];
#ifdef G6_PRODUCTION
        if (negotiated_suite != EYE_SUITE_EPHEMERAL) return 1;
#endif
        business_ready = 0;
        XTime_GetTime(&profile_started);
        body_ack[3] = negotiated_suite;
#ifdef G6_AUTO_RECOVERY
        ++diag_hello_attempt_count;
        ++diag_hello_ack_send_attempts;
        diag_hello_ack_send_status = UINT32_MAX;
        publish_rekey_diag();
#endif
        memcpy(hello, message, 48);
        int status = board_random(body_ack + 4, body + 4);
        if (!status) status = eye_control_encode(ack, sizeof ack, EYE_HELLO_ACK, body_ack, 36);
        if (!status) status = send_control(ack, sizeof ack);
#ifdef G6_AUTO_RECOVERY
        diag_hello_ack_send_status = (uint32_t)status;
#endif
        wipe(body_ack, sizeof body_ack);
        if (status) {
#ifdef G6_PRODUCTION
            fail_closed();
#endif
#ifdef G6_AUTO_RECOVERY
            publish_rekey_diag();
#endif
            return 1;
        }
        phase = WAIT_KEM;
#ifdef G6_AUTO_RECOVERY
        publish_rekey_diag();
#endif
        return 0;
    }
    if (phase == WAIT_KEM && type == EYE_HELLO && length == sizeof hello &&
        memcmp(hello, message, sizeof hello) == 0) {
#ifdef G6_AUTO_RECOVERY
        ++diag_hello_attempt_count;
        ++diag_hello_ack_send_attempts;
        diag_hello_ack_send_status = UINT32_MAX;
        publish_rekey_diag();
#endif
        int status = send_control(ack, sizeof ack);
#ifdef G6_AUTO_RECOVERY
        diag_hello_ack_send_status = (uint32_t)status;
        publish_rekey_diag();
#endif
        return status ? 1 : 0;
    }
    if (phase == WAIT_KEM && type == EYE_KEM_CIPHERTEXT && length == 780) {
        uint8_t shared[32], finished[44];
#ifdef G6_PRODUCTION
        int status = production_decapsulate(shared, body);
#else
        int status = eye_mlkem_dec(shared, body, private_key);
#endif
        if (!status) status = eye_session_begin(&session, shared, hello, ack, message);
        wipe(shared, sizeof shared);
        clear_handshake_cache();
        if (status || eye_session_board_finished(&session, finished) ||
            send_control(finished, sizeof finished)) {
            wipe(finished, sizeof finished);
            return 1;
        }
        wipe(finished, sizeof finished);
        phase = WAIT_FINISHED;
        return 0;
    }
    if (phase == WAIT_FINISHED && type == EYE_FINISHED_HOST && length == 44) {
        if (eye_session_verify_host_finished(&session, message)) return 1;
        if (negotiated_suite == EYE_SUITE_EPHEMERAL && !business_ready) {
            uint8_t coins[64] = {0};
            int status = ephemeral_coins(coins);
            if (!status) status = eye_ephemeral_offer(&ephemeral, &session, coins);
            wipe(coins, sizeof coins);
            if (!status) status = send_control(ephemeral.offer, sizeof ephemeral.offer);
            if (status) { eye_ephemeral_wipe(&ephemeral); return 1; }
            phase = WAIT_EPHEMERAL;
            return 0;
        }
        phase = WAIT_START;
        return 0;
    }
    if (phase == WAIT_EPHEMERAL && type == EYE_EPHEMERAL_REPLY) {
        uint8_t finished[44] = {0};
        int status = eye_ephemeral_complete(&ephemeral, &session, message, length);
        if (!status) status = eye_session_board_finished(&session, finished);
        if (!status) status = send_control(finished, sizeof finished);
        wipe(finished, sizeof finished);
        if (status) return 1;
        business_ready = 1;
        phase = WAIT_FINISHED;
        return 0;
    }
    if (phase == WAIT_START && type == EYE_START && length == 52) {
        if (negotiated_suite == EYE_SUITE_EPHEMERAL && !business_ready) return 1;
        if (eye_session_command(&session, message) || g3_usb_flush()) return 1;
        frame_id = 0;
        phase = STREAM;
        XTime_GetTime(&profile_started);
#ifdef G6_AUTO_RECOVERY
        publish_rekey_diag();
#endif
        return 0;
    }
    if (phase == STREAM && (type == EYE_STOP || type == EYE_REKEY) && length == 52) {
        if (eye_session_command(&session, message)) return 1;
#ifdef G6_SECURE_CLEANUP
        if (secure_cleanup()) {
            mark_fault();
            return 0;
        }
#else
        g3_usb_zeroize();
#endif
        clear_handshake_cache();
        phase = WAIT_HELLO;
#ifdef G6_AUTO_RECOVERY
        publish_rekey_diag();
#endif
        return 0;
    }
    return 1;
}
static int take_control(void *context, uint8_t *out, unsigned capacity) {
    (void)context;
    return usb_cdc_take_control(out, capacity);
}
static int process_control(void *context, const uint8_t *message, unsigned length) {
    (void)context;
#ifdef G6_DEV_USB_BOOTSTRAP
    if (eye_boot_prefix(message, length)) return bootstrap_control(message, length);
#endif
#ifdef G6_AUTO_RECOVERY
    ++diag_received_control_count;
#endif
    int status = handle_control(message, length);
#ifdef G6_AUTO_RECOVERY
    publish_rekey_diag();
#endif
    return status;
}
static int expire_profile(XTime now) {
    if (negotiated_suite != EYE_SUITE_EPHEMERAL || phase == WAIT_HELLO || phase == FAULT)
        return 0;
    uint64_t limit = phase == STREAM ? 1800U : 15U;
    if (now - profile_started < limit * (uint64_t)COUNTS_PER_SECOND) return 0;
    if (phase != STREAM) {
        fail_closed();
        return 1;
    }
    eye_session_rekey(&session);
#ifdef G6_SECURE_CLEANUP
    if (secure_cleanup()) { mark_fault(); return 1; }
#else
    g3_usb_zeroize();
#endif
    clear_handshake_cache();
    business_ready = 0;
    phase = WAIT_HELLO;
    return 1;
}
static int send_frame(const uint8_t *jpeg, unsigned size) {
    unsigned count = (size + 1399U) / 1400U;
    XTime ticks;
    XTime_GetTime(&ticks);
    uint64_t timestamp = ticks / (COUNTS_PER_SECOND / 1000000U);
    for (unsigned index = 0, offset = 0; index < count; ++index) {
        unsigned length = size - offset < 1400U ? size - offset : 1400U;
        uint64_t sequence = session.packet_sequence;
        uint8_t nonce[12];
        if (eye_session_next_nonce(&session, nonce)) return 1;
        wipe(nonce, sizeof nonce);
        struct eye_video_header h = {
            .version = 1, .flags = 1, .header_length = 40,
            .session_id = session.session_id, .frame_id = frame_id,
            .packet_id = index, .packet_count = count, .jpeg_length = size,
            .payload_length = length, .timestamp = timestamp,
            .packet_sequence = sequence
        };
        tx[0] = 2; be16(tx + 1, 40 + length + 16);
        if (eye_video_encode(tx + 3, 40, &h)) return 2;
        const uint8_t *sealed;
        if (g3_usb_encrypt(jpeg + offset, length, tx + 3, session.video_key,
                           session.nonce_prefix, sequence, &sealed)) return 3;
        memcpy(tx + 43, sealed, length + 16);
        if (usb_cdc_send(tx, 43 + length + 16)) return 4;
        offset += length;
    }
    g3_usb_zeroize();
    ++frame_id;
    ++g6_frames;
    return 0;
}

int main(void) {
#ifdef G6_PRODUCTION
    int status = initialize_production_startup();
    if (status) {
        g6_status = 0xffffffffU;
        xil_printf("G6_PRODUCTION_STARTUP_FAIL %d\r\n", status);
        for (;;) {}
    }
#else
    int status = g3_usb_init(CAMERA_CFG);
    if (!status) status = usb_cdc_init();
#endif
    if (status) { xil_printf("G6_INIT_FAIL %d\r\n", status); for (;;) {} }
#if !defined(G6_PRODUCTION) && !defined(G6_DEV_USB_BOOTSTRAP)
    while (g6_ready != PROVISION_MAGIC) {}
    for (unsigned i = 0; i < sizeof private_key; ++i) private_key[i] = g6_sk_load[i];
    for (unsigned i = 0; i < sizeof random_seed; ++i) random_seed[i] = g6_seed_load[i];
    wipe((void *)g6_sk_load, sizeof g6_sk_load);
    wipe((void *)g6_seed_load, sizeof g6_seed_load);
    if (eye_mlkem_check_sk(private_key) ||
        eye_session_init(&session, private_key + 768)) {
        wipe(private_key, sizeof private_key);
        wipe(random_seed, sizeof random_seed);
        g6_status = 0xffffffffU;
        for (;;) {}
    }
#endif
#ifdef G6_DEV_USB_BOOTSTRAP
    xil_printf("G6_DEV_USB_WAIT boot_mode=0x%02x\r\n", Xil_In32(0xf800025cU) & 15U);
#else
    g6_status = 1;
#endif
    int was_connected = 0, capture_errors = 0;
    uint32_t connection_epoch = usb_cdc_connection_epoch();
    uint8_t control[1036] = {0};
    for (;;) {
        uint32_t current_epoch = usb_cdc_connection_epoch();
#ifdef G6_DEV_USB_BOOTSTRAP
        if (usb_bootstrap.state != EYE_BOOT_READY) {
            uint64_t now_ms = bootstrap_now_ms();
            if (usb_bootstrap.state == EYE_BOOT_WAIT && current_epoch != connection_epoch &&
                    !usb_cdc_bootstrap_rx_interrupted()) bootstrap_wire_started = 0U;
            if (usb_bootstrap.state != EYE_BOOT_FAULT &&
                    (eye_boot_tick(&usb_bootstrap, now_ms, current_epoch, usb_cdc_ready()) ||
                     usb_cdc_bootstrap_rx_interrupted() ||
                     (bootstrap_wire_started && now_ms - bootstrap_wire_started >= 10000U)))
                fail_closed();
            if (!usb_cdc_ready()) continue;
            if (usb_cdc_bootstrap_rx_pending() && !bootstrap_wire_started)
                bootstrap_wire_started = now_ms ? now_ms : 1U;
            int length = usb_cdc_take_control(control, sizeof control);
            if (length) {
                bootstrap_wire_started = 0U;
                if (length < 0) fail_closed();
                else (void)bootstrap_control(control, (unsigned)length);
                wipe(control, sizeof control);
            }
            connection_epoch = current_epoch;
            continue;
        }
#endif
        if (current_epoch != connection_epoch) {
            retire_disconnected_session(UINT32_MAX, 0U,
                                        (unsigned)usb_cdc_ready(), current_epoch);
            was_connected = capture_errors = 0;
            connection_epoch = current_epoch;
            continue;
        }
        if (!usb_cdc_ready()) {
            if (was_connected) {
                retire_disconnected_session(UINT32_MAX, 0U, 0U, current_epoch);
                was_connected = 0;
            }
            continue;
        }
        was_connected = 1;
        if (phase == FAULT) continue;
        XTime now;
        XTime_GetTime(&now);
        if (expire_profile(now)) continue;
        if (eye_g6_control_dispatch(control, sizeof control,
                                    take_control, process_control, NULL) < 0) {
            if (!usb_cdc_ready() || usb_cdc_connection_epoch() != connection_epoch) {
                retire_disconnected_session(UINT32_MAX, 0U,
                    (unsigned)usb_cdc_ready(), usb_cdc_connection_epoch());
                was_connected = 0;
                connection_epoch = usb_cdc_connection_epoch();
            } else {
                ++g6_control_errors;
                fail_closed();
            }
            continue;
        }
        if (phase != STREAM) continue;
        const uint8_t *jpeg;
        unsigned size;
        if (g6_fault_inject == 1U) {
            g6_fault_inject = 0;
            ++g6_injected_capture_errors;
            status = 0xffffffffU; /* One-shot capture-status injection; DMA is untouched. */
        } else {
            status = g3_usb_capture(&jpeg, &size);
        }
        if (status) {
            ++g6_capture_errors;
            ++g6_dropped;
#ifdef G6_AUTO_RECOVERY
            if (status == 16U) {
                g6_auto_recovery_diag.state = 3U;
                fail_closed();
                continue;
            }
            if (status == 14U) {
                g6_auto_recovery_diag.state = 1U;
                g6_auto_recovery_diag.recovery_status = (uint32_t)(
                    secure_cleanup() ? 1 : g6_candidate_recover_camera());
                if (g6_auto_recovery_diag.recovery_status) {
                    g6_auto_recovery_diag.state = 3U;
                    mark_fault();
                    continue;
                }
                g6_auto_recovery_diag.state = 2U;
                eye_session_error(&session);
                clear_handshake_cache();
                frame_id = 0U;
                phase = WAIT_HELLO;
                capture_errors = 0;
                continue;
            }
            if (status == 15U) {
                ++g6_auto_recovery_diag.malformed_drop_count;
                if (g6_auto_action_for_status(status,
                        g6_auto_recovery_diag.malformed_drop_count) ==
                    G6_AUTO_ACTION_FAIL_CLOSED) {
                    g6_auto_recovery_diag.state = 3U;
                    fail_closed();
                } else if (secure_cleanup() || g6_candidate_recover_camera()) {
                    g6_auto_recovery_diag.state = 3U;
                    mark_fault();
                }
                continue;
            }
            g6_auto_recovery_diag.state = 3U;
            fail_closed();
            continue;
#endif
#ifdef G6_PRODUCTION
            fail_closed();
#else
            if (++capture_errors > 10 || g3_usb_flush()) fail_closed();
#endif
            continue;
        }
#ifdef G6_AUTO_RECOVERY
        g6_auto_recovery_diag.malformed_drop_count = 0U;
#endif
        capture_errors = 0;
        uint32_t send_epoch = usb_cdc_connection_epoch();
        status = send_frame(jpeg, size);
        int resume_status = g3_usb_resume();
#ifdef G6_AUTO_RECOVERY
        if (!status && !resume_status)
            g6_transport_failure_diag.last_successful_frame_id = frame_id - 1U;
#endif
        if (resume_status || status) {
            (void)handle_frame_send_failure((unsigned)status, (unsigned)resume_status,
                                             send_epoch);
            was_connected = 0;
            connection_epoch = usb_cdc_connection_epoch();
        }
    }
}
