/* M10 offline JTAG session exercise: ML-KEM Decaps -> HKDF -> Finished -> START. */
#include "xparameters.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "sleep.h"
#include "protocol.h"
#include "session.h"
#define MLK_CONFIG_PARAMETER_SET 512
#define MLK_CONFIG_NAMESPACE_PREFIX eye_mlkem
#define MLK_CONFIG_NO_RANDOMIZED_API
#define MLK_CONFIG_NO_SUPERCOP
#define MLK_CONFIG_NO_KEYPAIR_API
#define MLK_CONFIG_NO_ENCAPS_API
#include "mlkem/mlkem_native.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define MAGIC 0x30314d45U /* EM10 */
#define GCM_BASE 0x43c00000U
#define SK_BYTES 1632U
#define WIRE_BYTES 972U

struct m10_job {
    uint32_t magic, state, command, status, session_state, replay_rejected, nonce_count, zeroized;
    uint8_t material[56], board_finished[44], first_nonce[12], transcript[32], padding[80];
};
volatile struct m10_job m10_job __attribute__((aligned(64)));
volatile uint8_t m10_sk[SK_BYTES] __attribute__((aligned(64)));
volatile uint8_t m10_wire[WIRE_BYTES] __attribute__((aligned(64)));
static uint8_t private_key[SK_BYTES];
static struct eye_session session;
static int loaded;

_Static_assert(sizeof(struct m10_job) == 256, "M10 mailbox ABI");
_Static_assert(offsetof(struct m10_job, material) == 32, "M10 material offset");

static void wipe(volatile void *memory, unsigned n)
{
    volatile uint8_t *p = memory;
    while (n--) *p++ = 0;
}

static void pl_clear(void)
{
    Xil_Out32(GCM_BASE, 2); /* M08 zeroize/abort: old PL key and nonce. */
}

static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
           (uint32_t)p[2] << 8 | p[3];
}

static int pl_install(const uint8_t nonce[12])
{
    if (Xil_In32(GCM_BASE + 0x14) != 0x47434d31U) return -1;
    pl_clear();
    for (unsigned i = 0; i < 4; ++i)
        Xil_Out32(GCM_BASE + 0x20 + 4*i, be32(session.video_key + 4*i));
    for (unsigned i = 0; i < 3; ++i)
        Xil_Out32(GCM_BASE + 0x30 + 4*i, be32(nonce + 4*i));
    return 0;
}

static void clear_output(void)
{
    wipe(m10_job.material, 56 + 44 + 12 + 32);
    m10_job.replay_rejected = m10_job.nonce_count = m10_job.zeroized = 0;
}

static unsigned run_job(void)
{
    uint8_t shared[32] = {0}, hello[48] = {0}, ack[48] = {0}, kem[780] = {0};
    uint8_t host_finished[44] = {0}, start[52] = {0};
    uint8_t board_finished[44] = {0}, nonce[12] = {0};
    unsigned status = 0;
    clear_output();
    if (m10_job.command == 1) {
        pl_clear();
        wipe(private_key, SK_BYTES);
        loaded = 0;
        for (unsigned i = 0; i < SK_BYTES; ++i) private_key[i] = m10_sk[i];
        wipe(m10_sk, SK_BYTES);
        eye_session_reset(&session);
        if (eye_mlkem_check_sk(private_key) ||
            eye_session_init(&session, private_key + 768)) {
            wipe(private_key, SK_BYTES);
            return 2;
        }
        loaded = 1;
        return 0;
    }
    if (m10_job.command == 4) {
        if (!loaded) return 1;
        for (unsigned i = 0; i < 52; ++i) start[i] = m10_wire[i];
        wipe(m10_wire, WIRE_BYTES);
        if (eye_session_command(&session, start) || session.state != EYE_STATE_REKEY) {
            status = 10; goto fail;
        }
        wipe(start, sizeof start);
        pl_clear();
        m10_job.zeroized = 1;
        m10_job.session_state = session.state;
        return 0;
    }
    if (m10_job.command == 5) {
        eye_session_rekey(&session);
        pl_clear();
        wipe(private_key, SK_BYTES);
        wipe(m10_sk, SK_BYTES);
        loaded = 0;
        m10_job.zeroized = 1;
        m10_job.session_state = session.state;
        return 0;
    }
    if (!loaded) return 1;
    if (m10_job.command == 2) {
        for (unsigned i = 0; i < 48; ++i) hello[i] = m10_wire[i];
        for (unsigned i = 0; i < 48; ++i) ack[i] = m10_wire[48 + i];
        for (unsigned i = 0; i < 780; ++i) kem[i] = m10_wire[96 + i];
        wipe(m10_wire, WIRE_BYTES);
        if (eye_mlkem_dec(shared, kem + 12, private_key)) { status = 3; goto fail; }
        if (eye_session_begin(&session, shared, hello, ack, kem)) { status = 4; goto fail; }
        if (eye_session_board_finished(&session, board_finished)) { status = 5; goto fail; }
        for (unsigned i = 0; i < 16; ++i) m10_job.material[i] = session.video_key[i];
        for (unsigned i = 0; i < 32; ++i) m10_job.material[16 + i] = session.control_key[i];
        for (unsigned i = 0; i < 4; ++i) {
            m10_job.material[48 + i] = (uint8_t)(session.nonce_prefix >> (24 - 8*i));
            m10_job.material[52 + i] = (uint8_t)(session.session_id >> (24 - 8*i));
        }
        for (unsigned i = 0; i < 44; ++i) m10_job.board_finished[i] = board_finished[i];
        for (unsigned i = 0; i < 32; ++i) m10_job.transcript[i] = session.transcript_hash[i];
    } else if (m10_job.command == 3) {
        for (unsigned i = 0; i < 44; ++i) host_finished[i] = m10_wire[i];
        for (unsigned i = 0; i < 52; ++i) start[i] = m10_wire[44 + i];
        wipe(m10_wire, WIRE_BYTES);
        if (eye_session_verify_host_finished(&session, host_finished)) { status = 6; goto fail; }
        if (eye_session_command(&session, start)) { status = 7; goto fail; }
        if (eye_session_next_nonce(&session, nonce)) { status = 8; goto fail; }
        if (pl_install(nonce)) { status = 11; goto fail; }
        m10_job.replay_rejected = eye_session_accept_authenticated_packet(
            &session, session.session_id, 0) == 0 &&
            eye_session_accept_authenticated_packet(&session, session.session_id, 0) == EYE_SESSION_AUTH;
        if (!m10_job.replay_rejected) { status = 9; goto fail; }
        for (unsigned i = 0; i < 12; ++i) m10_job.first_nonce[i] = nonce[i];
        m10_job.nonce_count = 1;
    } else return 1;
    goto done;
fail:
    eye_session_error(&session);
    pl_clear();
done:
    m10_job.session_state = session.state;
    wipe(shared, sizeof shared);
    wipe(hello, sizeof hello); wipe(ack, sizeof ack); wipe(kem, sizeof kem);
    wipe(host_finished, sizeof host_finished); wipe(start, sizeof start);
    wipe(board_finished, sizeof board_finished); wipe(nonce, sizeof nonce);
    return status;
}

int main(void)
{
    Xil_DCacheDisable();
    usleep(1);
    m10_job.magic = MAGIC;
    xil_printf("M10 READY mailbox=%08x sk=%08x wire=%08x\r\n",
               (unsigned)(UINTPTR)&m10_job, (unsigned)(UINTPTR)m10_sk,
               (unsigned)(UINTPTR)m10_wire);
    for (;;) if (m10_job.state == 1) {
        m10_job.state = 4;
        m10_job.status = run_job();
        __asm__ volatile("dsb sy" ::: "memory");
        m10_job.state = m10_job.status ? 3 : 2;
    }
}
