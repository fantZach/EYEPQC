#include "session.h"
#include "protocol.h"
#include <tinycrypt/sha256.h>
#include <tinycrypt/constants.h>
#include <string.h>
#include <limits.h>

#define ROTATE_AT (UINT64_MAX - 65535ULL)

static void wipe(void *memory, size_t size)
{
    volatile uint8_t *p = memory;
    while (size--) *p++ = 0;
}

static uint32_t be32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
           (uint32_t)p[2] << 8 | p[3];
}

static uint64_t be64(const uint8_t *p)
{
    uint64_t n = 0;
    for (unsigned i = 0; i < 8; ++i) n = (n << 8) | p[i];
    return n;
}

static int equal32(const uint8_t *a, const uint8_t *b)
{
    volatile uint8_t difference = 0;
    for (unsigned i = 0; i < 32; ++i) difference |= a[i] ^ b[i];
    return difference == 0;
}

int eye_sha256(uint8_t out[32], const uint8_t *data, size_t length)
{
    struct tc_sha256_state_struct state;
    int okay;
    if (!out) return EYE_SESSION_INPUT;
    if (!data && length) {
        wipe(out, 32);
        return EYE_SESSION_INPUT;
    }
    okay = tc_sha256_init(&state) == TC_CRYPTO_SUCCESS &&
           (!length || tc_sha256_update(&state, data, length) == TC_CRYPTO_SUCCESS) &&
           tc_sha256_final(out, &state) == TC_CRYPTO_SUCCESS;
    wipe(&state, sizeof state);
    if (!okay) wipe(out, 32);
    return okay ? EYE_SESSION_OK : EYE_SESSION_INPUT;
}

static int hmac2(uint8_t out[32], const uint8_t *key, size_t key_length,
                 const uint8_t *a, size_t a_length, const uint8_t *b, size_t b_length)
{
    struct tc_sha256_state_struct state;
    uint8_t pad[64], inner[32];
    int okay = out && key && key_length && key_length <= 64 &&
               (!a_length || a) && (!b_length || b);
    if (!okay) {
        if (out) wipe(out, 32);
        return EYE_SESSION_INPUT;
    }
    memset(pad, 0x36, sizeof pad);
    for (size_t i = 0; i < key_length; ++i) pad[i] ^= key[i];
    okay = tc_sha256_init(&state) && tc_sha256_update(&state, pad, 64) &&
           (!a_length || tc_sha256_update(&state, a, a_length)) &&
           (!b_length || tc_sha256_update(&state, b, b_length)) &&
           tc_sha256_final(inner, &state);
    for (size_t i = 0; i < sizeof pad; ++i) pad[i] ^= 0x36 ^ 0x5c;
    okay = okay && tc_sha256_init(&state) && tc_sha256_update(&state, pad, 64) &&
           tc_sha256_update(&state, inner, 32) && tc_sha256_final(out, &state);
    wipe(&state, sizeof state); wipe(pad, sizeof pad); wipe(inner, sizeof inner);
    if (!okay) wipe(out, 32);
    return okay ? EYE_SESSION_OK : EYE_SESSION_INPUT;
}

int eye_hmac_sha256(uint8_t out[32], const uint8_t *key, size_t key_length,
                    const uint8_t *data, size_t length)
{
    return hmac2(out, key, key_length, data, length, NULL, 0);
}

int eye_hkdf56(uint8_t out[56], const uint8_t shared[32], const uint8_t salt[32])
{
    static const uint8_t info[] = "EYEPQC v1 keys";
    uint8_t prk[32], block[32], input[sizeof info];
    int status;
    if (!out) return EYE_SESSION_INPUT;
    if (!shared || !salt) {
        wipe(out, 56);
        return EYE_SESSION_INPUT;
    }
    status = hmac2(prk, salt, 32, shared, 32, NULL, 0);
    memcpy(input, info, sizeof info - 1);
    input[sizeof info - 1] = 1;
    if (!status) status = hmac2(block, prk, 32, input, sizeof input, NULL, 0);
    if (!status) {
        memcpy(out, block, 32);
        input[sizeof info - 1] = 2;
        status = hmac2(block, prk, 32, block, 32, input, sizeof input);
        if (!status) memcpy(out + 32, block, 24);
    }
    wipe(prk, sizeof prk); wipe(block, sizeof block); wipe(input, sizeof input);
    if (status) wipe(out, 56);
    return status;
}

void eye_session_reset(struct eye_session *s)
{
    if (s) wipe(s, sizeof *s);
}

static void close_session(struct eye_session *s, uint8_t state)
{
    if (s->state >= EYE_STATE_CONFIRM && s->state <= EYE_STATE_STREAMING)
        memcpy(s->last_transcript, s->transcript_hash, 32);
    wipe(s->transcript_hash, 32);
    wipe(s->video_key, 16);
    wipe(s->control_key, 32);
    s->nonce_prefix = s->session_id = 0;
    s->packet_sequence = s->command_sequence = 0;
    s->receive_high = s->receive_mask = 0;
    s->receive_started = s->board_finished_sent = s->host_finished_verified = 0;
    s->state = state;
}

void eye_session_rekey(struct eye_session *s)
{
    if (s) close_session(s, EYE_STATE_REKEY);
}

void eye_session_error(struct eye_session *s)
{
    if (s) close_session(s, EYE_STATE_ERROR);
}

int eye_session_init(struct eye_session *s, const uint8_t pk[800])
{
    if (!s) return EYE_SESSION_INPUT;
    eye_session_reset(s);
    if (!pk) return EYE_SESSION_INPUT;
    return eye_sha256(s->pinned_pk_hash, pk, 800);
}

int eye_session_begin(struct eye_session *s, const uint8_t shared[32],
                      const uint8_t hello[48], const uint8_t ack[48],
                      const uint8_t kem[780])
{
    static const uint8_t domain[] = "EYEPQC v1";
    struct tc_sha256_state_struct hash;
    const uint8_t *body;
    uint8_t type, derived[56], transcript[32];
    uint32_t length;
    int okay;
    if (!s) return EYE_SESSION_INPUT;
    if (!shared || !hello || !ack || !kem) {
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    if (s->state != EYE_STATE_IDLE && s->state != EYE_STATE_REKEY && s->state != EYE_STATE_ERROR)
        return EYE_SESSION_STATE;
    if (eye_control_decode(&type, &body, &length, hello, 48) || type != EYE_HELLO ||
        eye_control_decode(&type, &body, &length, ack, 48) || type != EYE_HELLO_ACK ||
        eye_control_decode(&type, &body, &length, kem, 780) || type != EYE_KEM_CIPHERTEXT)
        return EYE_SESSION_INPUT;
    s->state = EYE_STATE_HANDSHAKE;
    okay = tc_sha256_init(&hash) &&
           tc_sha256_update(&hash, domain, sizeof domain - 1) &&
           tc_sha256_update(&hash, s->pinned_pk_hash, 32) &&
           tc_sha256_update(&hash, hello, 48) && tc_sha256_update(&hash, ack, 48) &&
           tc_sha256_update(&hash, kem, 780) && tc_sha256_final(transcript, &hash);
    wipe(&hash, sizeof hash);
    if (!okay || equal32(transcript, s->last_transcript) ||
        eye_hkdf56(derived, shared, transcript)) {
        wipe(transcript, 32); wipe(derived, sizeof derived);
        eye_session_error(s);
        return EYE_SESSION_AUTH;
    }
    memcpy(s->transcript_hash, transcript, 32);
    memcpy(s->video_key, derived, 16);
    memcpy(s->control_key, derived + 16, 32);
    s->nonce_prefix = be32(derived + 48);
    s->session_id = be32(derived + 52);
    s->state = EYE_STATE_CONFIRM;
    wipe(transcript, 32); wipe(derived, sizeof derived);
    return EYE_SESSION_OK;
}

static int finished(uint8_t out[32], const struct eye_session *s,
                    const uint8_t *label, size_t label_length)
{
    return hmac2(out, s->control_key, 32, label, label_length, s->transcript_hash, 32);
}

int eye_session_board_finished(struct eye_session *s, uint8_t out[44])
{
    static const uint8_t label[] = "board finished";
    uint8_t tag[32];
    int status;
    if (!s) return EYE_SESSION_INPUT;
    if (!out) {
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    if (s->state != EYE_STATE_CONFIRM || s->board_finished_sent) return EYE_SESSION_STATE;
    status = finished(tag, s, label, sizeof label - 1);
    if (!status && eye_control_encode(out, 44, EYE_FINISHED_BOARD, tag, 32))
        status = EYE_SESSION_INPUT;
    wipe(tag, sizeof tag);
    if (!status) s->board_finished_sent = 1;
    else eye_session_error(s);
    return status;
}

int eye_session_verify_host_finished(struct eye_session *s, const uint8_t message[44])
{
    static const uint8_t label[] = "host finished";
    uint8_t tag[32] = {0}, type;
    uint32_t length;
    const uint8_t *body;
    int status;
    if (!s) return EYE_SESSION_INPUT;
    if (!message) {
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    if (s->state != EYE_STATE_CONFIRM || !s->board_finished_sent || s->host_finished_verified)
        return EYE_SESSION_STATE;
    if (eye_control_decode(&type, &body, &length, message, 44) || type != EYE_FINISHED_HOST) {
        wipe(tag, sizeof tag);
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    status = finished(tag, s, label, sizeof label - 1);
    if (!status && !equal32(tag, body)) status = EYE_SESSION_AUTH;
    wipe(tag, sizeof tag);
    if (status) eye_session_error(s);
    else s->host_finished_verified = 1;
    return status;
}

int eye_session_command(struct eye_session *s, const uint8_t message[52])
{
    static const uint8_t label[] = "host command";
    uint8_t tag[32], context[sizeof label - 1 + 32], type;
    uint32_t length;
    const uint8_t *body;
    uint64_t sequence;
    int status;
    if (!s) return EYE_SESSION_INPUT;
    if (!message) {
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    if (eye_control_decode(&type, &body, &length, message, 52) ||
        (type != EYE_START && type != EYE_STOP && type != EYE_REKEY)) {
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    if ((type == EYE_START && (s->state != EYE_STATE_CONFIRM || !s->host_finished_verified)) ||
        (type != EYE_START && s->state != EYE_STATE_STREAMING)) return EYE_SESSION_STATE;
    sequence = be64(body);
    if (sequence != s->command_sequence || sequence == UINT64_MAX) {
        eye_session_error(s);
        return EYE_SESSION_AUTH;
    }
    memcpy(context, label, sizeof label - 1);
    memcpy(context + sizeof label - 1, s->transcript_hash, 32);
    status = hmac2(tag, s->control_key, 32, context, sizeof context, message, 20);
    wipe(context, sizeof context);
    if (!status && !equal32(tag, body + 8)) status = EYE_SESSION_AUTH;
    wipe(tag, sizeof tag);
    if (status) { eye_session_error(s); return status; }
    ++s->command_sequence;
    if (type == EYE_START) s->state = EYE_STATE_STREAMING;
    else close_session(s, type == EYE_REKEY ? EYE_STATE_REKEY : EYE_STATE_IDLE);
    return EYE_SESSION_OK;
}

int eye_session_next_nonce(struct eye_session *s, uint8_t out[12])
{
    if (!s) return EYE_SESSION_INPUT;
    if (!out) {
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    if (s->state != EYE_STATE_STREAMING) return EYE_SESSION_STATE;
    if (s->packet_sequence >= ROTATE_AT) {
        eye_session_rekey(s);
        return EYE_SESSION_ROTATE;
    }
    if (eye_nonce_encode(out, 12, s->nonce_prefix, s->packet_sequence)) {
        eye_session_error(s);
        return EYE_SESSION_INPUT;
    }
    ++s->packet_sequence;
    return EYE_SESSION_OK;
}

int eye_session_accept_authenticated_packet(struct eye_session *s,
                                            uint32_t session_id, uint64_t sequence)
{
    uint64_t distance, bit;
    if (!s) return EYE_SESSION_INPUT;
    if (s->state != EYE_STATE_STREAMING || session_id != s->session_id)
        return EYE_SESSION_STATE;
    if (!s->receive_started) {
        s->receive_started = 1; s->receive_high = sequence; s->receive_mask = 1;
        return EYE_SESSION_OK;
    }
    if (sequence > s->receive_high) {
        distance = sequence - s->receive_high;
        s->receive_mask = distance >= 64 ? 1 : (s->receive_mask << distance) | 1;
        s->receive_high = sequence;
        return EYE_SESSION_OK;
    }
    distance = s->receive_high - sequence;
    if (distance >= 64) return EYE_SESSION_AUTH;
    bit = 1ULL << distance;
    if (s->receive_mask & bit) return EYE_SESSION_AUTH;
    s->receive_mask |= bit;
    return EYE_SESSION_OK;
}
