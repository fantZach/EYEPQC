#ifndef EYEPQC_G6_DEV_BOOTSTRAP_H
#define EYEPQC_G6_DEV_BOOTSTRAP_H

#include <stdint.h>
#include <string.h>
#include "g6_control_dispatch.h"

#define EYE_BOOT_TOTAL 1696U
#define EYE_BOOT_HEADER 12U
#define EYE_BOOT_ACK 46U
enum eye_boot_state { EYE_BOOT_WAIT, EYE_BOOT_RECV, EYE_BOOT_READY, EYE_BOOT_FAULT };
struct eye_bootstrap {
    uint8_t material[EYE_BOOT_TOTAL], public_pin[32];
    uint32_t received, epoch;
    uint64_t started_ms;
    enum eye_boot_state state;
};
typedef int (*eye_boot_activate)(const uint8_t pin[32], const uint8_t sk[1632],
                                  const uint8_t seed[32]);

static inline unsigned eye_boot_u16(const uint8_t *p) { return (unsigned)p[0] << 8 | p[1]; }
static inline void eye_boot_put16(uint8_t *p, unsigned n) { p[0] = n >> 8; p[1] = n; }
static inline int eye_boot_prefix(const uint8_t *p, unsigned n)
{
    return n >= 4U && memcmp(p, "EYBS", 4U) == 0;
}
static inline void eye_boot_fault(struct eye_bootstrap *b)
{
    eye_g6_control_wipe(b->material, sizeof b->material);
    eye_g6_control_wipe(b->public_pin, sizeof b->public_pin);
    b->received = b->epoch = 0U;
    b->started_ms = 0U;
    b->state = EYE_BOOT_FAULT;
}
static inline int eye_boot_tick(struct eye_bootstrap *b, uint64_t now_ms,
                                 uint32_t epoch, int ready)
{
    if (b->state == EYE_BOOT_RECV &&
            (!ready || epoch != b->epoch || now_ms - b->started_ms >= 10000U)) {
        eye_boot_fault(b);
        return -1;
    }
    return 0;
}
static inline int eye_boot_process(struct eye_bootstrap *b, const uint8_t *p,
                                   unsigned n, uint64_t now_ms, uint32_t epoch,
                                   eye_boot_activate activate)
{
    unsigned length, offset;
    if (eye_boot_tick(b, now_ms, epoch, 1)) return -1;
    if (!p || n < EYE_BOOT_HEADER || !eye_boot_prefix(p, n) || p[4] != 1U ||
            eye_boot_u16(p + 10) != EYE_BOOT_TOTAL) goto invalid;
    length = eye_boot_u16(p + 8);
    offset = eye_boot_u16(p + 6);
    if (n != EYE_BOOT_HEADER + length) goto invalid;
    if (p[5] == 1U && !length && !offset) return 0;
    if (p[5] != 2U || b->state >= EYE_BOOT_READY || !length || length > 1024U ||
            offset != b->received || offset + length > EYE_BOOT_TOTAL) goto invalid;
    if (b->state == EYE_BOOT_WAIT) {
        b->state = EYE_BOOT_RECV;
        b->epoch = epoch;
        b->started_ms = now_ms;
    }
    if (eye_boot_tick(b, now_ms, epoch, 1)) return -1;
    memcpy(b->material + offset, p + EYE_BOOT_HEADER, length);
    b->received += length;
    if (b->received == EYE_BOOT_TOTAL) {
        if (!activate || activate(b->material, b->material + 32U,
                                  b->material + 1664U)) goto invalid;
        memcpy(b->public_pin, b->material, 32U);
        eye_g6_control_wipe(b->material, sizeof b->material);
        b->state = EYE_BOOT_READY;
    }
    return 0;
invalid:
    eye_boot_fault(b);
    return -1;
}
static inline void eye_boot_reply(const struct eye_bootstrap *b, uint8_t out[EYE_BOOT_ACK])
{
    memset(out, 0, EYE_BOOT_ACK);
    memcpy(out, "EYBS", 4U);
    out[4] = 1U; out[5] = 0x81U;
    eye_boot_put16(out + 6, b->received);
    eye_boot_put16(out + 8, 34U);
    eye_boot_put16(out + 10, EYE_BOOT_TOTAL);
    out[12] = (uint8_t)b->state;
    out[13] = b->state == EYE_BOOT_FAULT ? 1U : 0U;
    if (b->state == EYE_BOOT_READY) memcpy(out + 14, b->public_pin, 32U);
}
#endif
