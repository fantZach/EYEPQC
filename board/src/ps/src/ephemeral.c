#include "ephemeral.h"
#include "protocol.h"
#include "g6_control_dispatch.h"
#define MLK_CONFIG_PARAMETER_SET 512
#define MLK_CONFIG_NAMESPACE_PREFIX eye_mlkem
#define MLK_CONFIG_NO_RANDOMIZED_API
#define MLK_CONFIG_NO_SUPERCOP
#define MLK_CONFIG_NO_ENCAPS_API
#include "mlkem/mlkem_native.h"
#include <string.h>

void eye_ephemeral_wipe(struct eye_ephemeral *e)
{
    if (e) eye_g6_control_wipe(e, sizeof *e);
}

static int equal(const uint8_t *a, const uint8_t *b)
{
    volatile uint8_t difference = 0;
    for (unsigned i = 0; i < 32; ++i) difference |= a[i] ^ b[i];
    return difference == 0;
}

static int fail(struct eye_ephemeral *e, struct eye_session *s)
{
    eye_ephemeral_wipe(e);
    eye_session_error(s);
    return EYE_SESSION_AUTH;
}

int eye_ephemeral_offer(struct eye_ephemeral *e, struct eye_session *s,
                         const uint8_t coins[64])
{
    static const uint8_t label[] = "EYEPQC eph offer v1";
    uint8_t input[sizeof label - 1 + 32 + 844], body[864] = {0};
    int status;
    if (!e || !s || !coins || e->active || s->state != EYE_STATE_CONFIRM ||
        !s->host_finished_verified) return fail(e, s);
    memcpy(body, s->transcript_hash, 32);
    status = eye_mlkem_keypair_derand(body + 32, e->private_key, coins);
    if (!status) status = eye_control_encode(e->offer, sizeof e->offer, EYE_EPHEMERAL_OFFER, body, sizeof body);
    memcpy(input, label, sizeof label - 1);
    memcpy(input + sizeof label - 1, s->transcript_hash, 32);
    memcpy(input + sizeof label - 1 + 32, e->offer, 844);
    if (!status) status = eye_hmac_sha256(e->offer + 844, s->control_key, 32, input, sizeof input);
    eye_g6_control_wipe(input, sizeof input);
    eye_g6_control_wipe(body, sizeof body);
    if (status) return fail(e, s);
    /* Bootstrap must never encrypt video, even while the reply is pending. */
    eye_g6_control_wipe(s->video_key, sizeof s->video_key);
    e->active = 1;
    return 0;
}

int eye_ephemeral_complete(struct eye_ephemeral *e, struct eye_session *s,
                            const uint8_t *reply, size_t length)
{
    static const uint8_t mac_label[] = "EYEPQC eph reply v1";
    static const uint8_t th_label[] = "EYEPQC eph business v1";
    uint8_t input[sizeof th_label - 1 + 32 + 876 + 844];
    uint8_t tag[32] = {0}, shared[32] = {0}, transcript[32] = {0}, type;
    uint32_t body_length;
    const uint8_t *body;
    int status;
    if (!e || !s || !reply || !e->active || length != EYE_EPHEMERAL_REPLY_BYTES ||
        s->state != EYE_STATE_CONFIRM || !s->host_finished_verified ||
        eye_control_decode(&type, &body, &body_length, reply, length) ||
        type != EYE_EPHEMERAL_REPLY || !equal(body, s->transcript_hash)) return fail(e, s);
    memcpy(input, mac_label, sizeof mac_label - 1);
    memcpy(input + sizeof mac_label - 1, s->transcript_hash, 32);
    memcpy(input + sizeof mac_label - 1 + 32, e->offer, 876);
    memcpy(input + sizeof mac_label - 1 + 32 + 876, reply, 812);
    status = eye_hmac_sha256(tag, s->control_key, 32, input, sizeof mac_label - 1 + 32 + 876 + 812);
    if (!status && !equal(tag, body + 800)) status = EYE_SESSION_AUTH;
    if (!status) status = eye_mlkem_dec(shared, body + 32, e->private_key);
    if (!status) {
        memcpy(input, th_label, sizeof th_label - 1);
        memcpy(input + sizeof th_label - 1, s->transcript_hash, 32);
        memcpy(input + sizeof th_label - 1 + 32, e->offer, 876);
        memcpy(input + sizeof th_label - 1 + 32 + 876, reply, 844);
        status = eye_sha256(transcript, input, sizeof input);
    }
    if (!status) status = eye_session_bind_ephemeral(s, shared, transcript);
    eye_g6_control_wipe(input, sizeof input);
    eye_g6_control_wipe(tag, sizeof tag);
    eye_g6_control_wipe(shared, sizeof shared);
    eye_g6_control_wipe(transcript, sizeof transcript);
    eye_ephemeral_wipe(e);
    return status ? fail(e, s) : 0;
}
