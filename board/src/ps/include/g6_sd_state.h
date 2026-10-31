#ifndef EYEPQC_G6_SD_STATE_H
#define EYEPQC_G6_SD_STATE_H
#include <stddef.h>
#include <stdint.h>
#define EYE_SD_SLOT_BYTES 80U
struct eye_sd_ops {
    int (*read)(unsigned slot, uint8_t out[EYE_SD_SLOT_BYTES]);
    int (*write_sync)(unsigned slot, const uint8_t data[EYE_SD_SLOT_BYTES]);
};
struct eye_sd_state {
    uint8_t secret[32];
    uint8_t public_pin[32];
    uint64_t generation;
    unsigned slot;
    int ready;
};
int eye_sd_state_open(struct eye_sd_state *state, const struct eye_sd_ops *ops,
                      const uint8_t public_pin[32]);
int eye_sd_state_random(struct eye_sd_state *state, const struct eye_sd_ops *ops,
                        uint8_t *out, size_t length, const uint8_t additional[32]);
void eye_sd_state_wipe(struct eye_sd_state *state);
#endif
