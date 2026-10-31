/* Experimental persistent DRBG state; no fresh entropy or rollback protection. */
#include "g6_sd_state.h"
#include "g6_hmac_drbg.h"
#include "session.h"
#include "tinycrypt/sha256.h"
#include <string.h>

static void wipe(void *p, size_t n) {
    volatile uint8_t *v = p;
    while (n--) *v++ = 0;
}
void eye_sd_state_wipe(struct eye_sd_state *s) { if (s) wipe(s, sizeof *s); }
static void be64(uint8_t *p, uint64_t v) {
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(v >> (56U - 8U*i));
}
static uint64_t u64(const uint8_t *p) {
    uint64_t v = 0;
    for (unsigned i = 0; i < 8; ++i) v = (v << 8) | p[i];
    return v;
}
static int hash(uint8_t out[32], const uint8_t *p, size_t n) {
    struct tc_sha256_state_struct ctx;
    int ok = tc_sha256_init(&ctx) && tc_sha256_update(&ctx, p, n) &&
             tc_sha256_final(out, &ctx);
    wipe(&ctx, sizeof ctx);
    return !ok;
}
static int valid(const uint8_t p[80]) {
    uint8_t digest[32];
    int bad = memcmp(p, "EYERNG01", 8) || hash(digest, p, 48);
    if (!bad) bad = memcmp(digest, p + 48, 32);
    wipe(digest, sizeof digest);
    return !bad;
}
static int advance(uint8_t out[32], const uint8_t secret[32], uint64_t generation,
                   const uint8_t pin[32]) {
    uint8_t input[64] = {0};
    memcpy(input, "EYEPQC SD advance v1", sizeof("EYEPQC SD advance v1") - 1U);
    be64(input + 24, generation);
    memcpy(input + 32, pin, 32);
    int bad = eye_hmac_sha256(out, secret, 32, input, sizeof input);
    wipe(input, sizeof input);
    return bad;
}
int eye_sd_state_open(struct eye_sd_state *s, const struct eye_sd_ops *ops,
                      const uint8_t public_pin[32]) {
    uint8_t slots[2][80] = {{0}};
    uint8_t expected[32] = {0};
    int status = 1;
    if (!s) return 1;
    eye_sd_state_wipe(s);
    if (!public_pin || !ops || !ops->read || !ops->write_sync ||
        ops->read(0, slots[0]) || ops->read(1, slots[1]) ||
        !valid(slots[0]) || !valid(slots[1])) goto done;
    uint64_t a = u64(slots[0] + 8), b = u64(slots[1] + 8);
    unsigned current = a >= b ? 0U : 1U;
    if (a == b) {
        if (a != 0U || memcmp(slots[0], slots[1], 80)) goto done;
    } else {
        unsigned older = current ^ 1U;
        if ((a > b ? a - b : b - a) != 1U ||
            advance(expected, slots[older] + 16, u64(slots[older] + 8), public_pin) ||
            memcmp(expected, slots[current] + 16, 32)) goto done;
    }
    s->generation = current ? b : a;
    s->slot = current;
    memcpy(s->secret, slots[current] + 16, 32);
    memcpy(s->public_pin, public_pin, 32);
    s->ready = 1;
    status = 0;
done:
    wipe(slots, sizeof slots);
    wipe(expected, sizeof expected);
    return status;
}
int eye_sd_state_random(struct eye_sd_state *s, const struct eye_sd_ops *ops,
                        uint8_t *out, size_t length, const uint8_t additional[32]) {
    struct eye_hmac_drbg drbg = {0};
    uint8_t material[64] = {0}, next[80] = {0}, readback[80] = {0}, nonce[16] = {0};
    uint8_t personalization[52] = {0};
    int status = 1;
    if (out && length <= 64U) wipe(out, length);
    if (!s || !ops || !ops->read || !ops->write_sync || !out || !additional ||
        !length || length > 64U || !s->ready || s->generation == UINT64_MAX) goto done;
    memcpy(nonce, "EYERNG01", 8);
    be64(nonce + 8, s->generation);
    memcpy(personalization, "EYEPQC SD ratchet v1", 20);
    memcpy(personalization + 20, s->public_pin, 32);
    if (eye_hmac_drbg_instantiate(&drbg, 256U, s->secret, 32U, nonce, 16U,
                                  personalization, sizeof personalization) ||
        eye_hmac_drbg_generate(&drbg, material, length, additional, 32U)) goto done;
    memcpy(next, "EYERNG01", 8);
    be64(next + 8, s->generation + 1U);
    if (advance(next + 16, s->secret, s->generation, s->public_pin)) goto done;
    if (hash(next + 48, next, 48)) goto done;
    unsigned target = s->slot ^ 1U;
    /* No output may escape until the advanced state is synced and read back.
     * shortcut: SD controller durability and whole-card rollback need hardware support. */
    if (ops->write_sync(target, next) || ops->read(target, readback) ||
        memcmp(next, readback, sizeof next)) goto done;
    memcpy(s->secret, next + 16, 32);
    ++s->generation;
    s->slot = target;
    memcpy(out, material, length);
    status = 0;
done:
    eye_hmac_drbg_uninstantiate(&drbg);
    wipe(material, sizeof material); wipe(next, sizeof next);
    wipe(readback, sizeof readback); wipe(nonce, sizeof nonce);
    wipe(personalization, sizeof personalization);
    if (status) eye_sd_state_wipe(s);
    return status;
}
