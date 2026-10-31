#include "g6_sd_state.h"
#include "session.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t disk[2][80];
static int failure, written;
static void seal(uint8_t p[80]) { assert(!eye_sha256(p + 48, p, 48)); }
static int read_slot(unsigned slot, uint8_t out[80]) {
    if (failure == 4 && written) return 1;
    memcpy(out, disk[slot], 80);
    if (failure == 5 && written) out[16] ^= 1;
    return 0;
}
static int write_slot(unsigned slot, const uint8_t p[80]) {
    if (failure == 1) return 1;
    written = 1;
    if (failure == 2) { memcpy(disk[slot], p, 24); return 1; }
    memcpy(disk[slot], p, 80);
    return failure == 3;
}
static const struct eye_sd_ops ops = {read_slot, write_slot};
static const uint8_t pin[32] = {1};
static void setup(void) {
    memset(disk, 0, sizeof disk);
    memcpy(disk[0], "EYERNG01", 8);
    memset(disk[0] + 16, 0x61, 32);
    seal(disk[0]);
    memcpy(disk[1], disk[0], 80);
    failure = written = 0;
}
static int zero(const uint8_t *p, size_t n) {
    for (size_t i = 0; i < n; ++i) if (p[i]) return 0;
    return 1;
}
int main(void) {
    struct eye_sd_state state;
    uint8_t outputs[30][64], additional[32] = {0};
    setup();
    for (unsigned i = 0; i < 30; ++i) {
        assert(!eye_sd_state_open(&state, &ops, pin));
        assert(state.generation == i);
        assert(!eye_sd_state_random(&state, &ops, outputs[i], 64, additional));
        assert(state.generation == i + 1U);
        for (unsigned j = 0; j < i; ++j) assert(memcmp(outputs[i], outputs[j], 64));
        eye_sd_state_wipe(&state);
    }
    for (int mode = 1; mode <= 5; ++mode) {
        uint8_t out[32];
        setup();
        assert(!eye_sd_state_open(&state, &ops, pin));
        failure = mode;
        memset(out, 0x11, sizeof out);
        assert(eye_sd_state_random(&state, &ops, out, sizeof out, additional));
        assert(zero(out, sizeof out) && zero((uint8_t *)&state, sizeof state));
        failure = written = 0;
        int status = eye_sd_state_open(&state, &ops, pin);
        if (mode == 2) assert(status); /* Never fall back from a torn latest slot. */
        else {
            assert(!status);
            assert(state.generation == (mode == 1 ? 0U : 1U));
            assert(!eye_sd_state_random(&state, &ops, out, sizeof out, additional));
        }
    }
    setup(); disk[0][16] ^= 1;
    assert(eye_sd_state_open(&state, &ops, pin));
    setup(); disk[1][15] = 2; seal(disk[1]);
    assert(eye_sd_state_open(&state, &ops, pin));
    setup(); disk[1][15] = 1; seal(disk[1]); /* Adjacent but unrelated secret. */
    assert(eye_sd_state_open(&state, &ops, pin));
    setup();
    assert(!eye_sd_state_open(&state, &ops, pin));
    assert(!eye_sd_state_random(&state, &ops, outputs[0], 64, additional));
    uint8_t other_pin[32] = {2};
    assert(eye_sd_state_open(&state, &ops, other_pin));
    setup(); disk[1][16] ^= 1; seal(disk[1]);
    assert(eye_sd_state_open(&state, &ops, pin));
    setup(); disk[0][15] = disk[1][15] = 1; seal(disk[0]); seal(disk[1]);
    assert(eye_sd_state_open(&state, &ops, pin));
    setup();
    assert(!eye_sd_state_open(&state, &ops, pin));
    state.generation = UINT64_MAX;
    memset(outputs[0], 1, 32);
    assert(eye_sd_state_random(&state, &ops, outputs[0], 32, additional));
    assert(zero(outputs[0], 32) && !state.ready);
    puts("G6_SD_STATE_PASS reboot=30 failure_modes=5 corrupt_mix_overflow=PASS");
    return 0;
}
