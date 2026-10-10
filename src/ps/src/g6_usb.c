/* Development G6: JTAG-provisioned secret/seed, real USB ML-KEM session. */
#include "xil_printf.h"
#ifdef SDT
#include "xiltimer.h"
#else
#include "xtime_l.h"
#endif
#include "session.h"
#include "protocol.h"
#include "g6_control_dispatch.h"
#define MLK_CONFIG_PARAMETER_SET 512
#define MLK_CONFIG_NAMESPACE_PREFIX eye_mlkem
#define MLK_CONFIG_NO_RANDOMIZED_API
#define MLK_CONFIG_NO_SUPERCOP
#define MLK_CONFIG_NO_KEYPAIR_API
#define MLK_CONFIG_NO_ENCAPS_API
#include "mlkem/mlkem_native.h"
#include <stdint.h>
#include <string.h>

#define PROVISION_MAGIC 0x36475345U
#define CAMERA_CFG ((1U << 25) | (1000U << 9) | (12U << 3) | 4U | 2U)

int g3_usb_init(unsigned camera_cfg);
int g3_usb_capture(const uint8_t **data, unsigned *size);
int g3_usb_flush(void);
int g3_usb_resume(void);
void g3_usb_zeroize(void);
int g3_usb_encrypt(const uint8_t *plain, unsigned size, const uint8_t aad[40],
                   const uint8_t key[16], uint32_t epoch, uint64_t sequence,
                   const uint8_t **sealed);
int usb_cdc_init(void);
int usb_cdc_ready(void);
uint32_t usb_cdc_connection_epoch(void);
int usb_cdc_send(uint8_t *data, uint32_t size);
int usb_cdc_take_control(uint8_t *out, uint32_t capacity);

volatile uint8_t g6_sk_load[1632] __attribute__((aligned(64)));
volatile uint8_t g6_seed_load[32] __attribute__((aligned(64)));
volatile uint32_t g6_ready __attribute__((aligned(64)));
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

static uint8_t private_key[1632], random_seed[32];
static uint8_t hello[48], ack[48], tx[3 + 1456] __attribute__((aligned(64)));
static struct eye_session session;
static uint64_t random_counter;
static uint32_t frame_id;

enum phase { WAIT_HELLO, WAIT_KEM, WAIT_FINISHED, WAIT_START, STREAM, FAULT };
static enum phase phase;

static void wipe(void *p, unsigned length) {
    eye_g6_control_wipe(p, length);
}
static void clear_handshake_cache(void) {
    wipe(hello, sizeof hello);
    wipe(ack, sizeof ack);
}
static void be16(uint8_t *p, unsigned n) { p[0] = n >> 8; p[1] = n; }
static void be64(uint8_t *p, uint64_t n) {
    for (unsigned i = 0; i < 8; ++i) p[i] = n >> (56 - 8*i);
}
static int send_control(const uint8_t *message, unsigned length) {
    if (length < 12 || length > 1036) return 1;
    tx[0] = 1; be16(tx + 1, length);
    memcpy(tx + 3, message, length);
    return usb_cdc_send(tx, length + 3);
}
static int board_random(uint8_t out[32], const uint8_t host_random[32]) {
    uint8_t input[40];
    memcpy(input, host_random, 32);
    be64(input + 32, random_counter++);
    int status = eye_hmac_sha256(out, random_seed, sizeof random_seed, input, sizeof input);
    wipe(input, sizeof input);
    return status;
}
static void fail_closed(void) {
    g3_usb_zeroize();
    eye_session_error(&session);
    clear_handshake_cache();
    phase = FAULT;
    ++g6_fatal_errors;
    ++g6_status;
}
static int handle_control(const uint8_t *message, unsigned length) {
    uint8_t type, body_ack[36] = {1, 1, 0, 1};
    const uint8_t *body;
    uint32_t body_length;
    if (eye_control_decode(&type, &body, &body_length, message, length)) return 1;
    if (phase == WAIT_HELLO && type == EYE_HELLO && length == 48) {
        memcpy(hello, message, 48);
        int status = board_random(body_ack + 4, body + 4);
        if (!status) status = eye_control_encode(ack, sizeof ack, EYE_HELLO_ACK, body_ack, 36);
        if (!status) status = send_control(ack, sizeof ack);
        wipe(body_ack, sizeof body_ack);
        if (status) return 1;
        phase = WAIT_KEM;
        return 0;
    }
    if (phase == WAIT_KEM && type == EYE_KEM_CIPHERTEXT && length == 780) {
        uint8_t shared[32], finished[44];
        int status = eye_mlkem_dec(shared, body, private_key);
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
        phase = WAIT_START;
        return 0;
    }
    if (phase == WAIT_START && type == EYE_START && length == 52) {
        if (eye_session_command(&session, message) || g3_usb_flush()) return 1;
        frame_id = 0;
        phase = STREAM;
        return 0;
    }
    if (phase == STREAM && (type == EYE_STOP || type == EYE_REKEY) && length == 52) {
        if (eye_session_command(&session, message)) return 1;
        g3_usb_zeroize();
        clear_handshake_cache();
        phase = WAIT_HELLO;
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
    return handle_control(message, length);
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
    int status = g3_usb_init(CAMERA_CFG);
    if (!status) status = usb_cdc_init();
    if (status) { xil_printf("G6_INIT_FAIL %d\r\n", status); for (;;) {} }
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
    g6_status = 1;
    int was_connected = 0, capture_errors = 0;
    uint32_t connection_epoch = usb_cdc_connection_epoch();
    uint8_t control[1036] = {0};
    for (;;) {
        uint32_t current_epoch = usb_cdc_connection_epoch();
        if (current_epoch != connection_epoch) {
            g3_usb_zeroize();
            eye_session_error(&session);
            clear_handshake_cache();
            phase = WAIT_HELLO;
            was_connected = capture_errors = 0;
            connection_epoch = current_epoch;
            ++g6_disconnects;
        }
        if (!usb_cdc_ready()) {
            if (was_connected) {
                g3_usb_zeroize();
                eye_session_error(&session);
                clear_handshake_cache();
                phase = WAIT_HELLO;
                was_connected = 0;
                ++g6_disconnects;
            }
            continue;
        }
        was_connected = 1;
        if (phase == FAULT) continue;
        if (eye_g6_control_dispatch(control, sizeof control,
                                    take_control, process_control, NULL) < 0) {
            ++g6_control_errors;
            fail_closed();
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
            if (++capture_errors > 10 || g3_usb_flush()) fail_closed();
            continue;
        }
        capture_errors = 0;
        status = send_frame(jpeg, size);
        if (g3_usb_resume() || status) {
            ++g6_transport_errors;
            fail_closed();
        }
    }
}
