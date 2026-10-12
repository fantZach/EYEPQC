#ifndef EYEPQC_MLKEM_KECCAK_ADAPTER_H
#define EYEPQC_MLKEM_KECCAK_ADAPTER_H

#include "keccak_accel.h"

typedef void (*mlkem_keccak_fallback_fn)(uint64_t state[25]);

typedef enum {
    MLKEM_KECCAK_HARDWARE = 0,
    MLKEM_KECCAK_SOFTWARE_FALLBACK = 1,
    MLKEM_KECCAK_NO_FALLBACK = -1
} mlkem_keccak_backend;

/* Pass mlk_keccakf1600_permute as software_fallback at the eventual PS callsite.
 * The supplied permutation routine and third-party sources remain unmodified. */
mlkem_keccak_backend mlkem_keccakf1600_accel_or_fallback(
    const keccak_accel_io *io, uint64_t state[25], uint32_t poll_limit,
    mlkem_keccak_fallback_fn software_fallback);

/* Internal fast path. Caller must bind this call to a context whose ID and
 * version were checked during backend configuration. */
mlkem_keccak_backend mlkem_keccakf1600_accel_or_fallback_prevalidated(
    const keccak_accel_io *io, uint64_t state[25], uint32_t poll_limit,
    mlkem_keccak_fallback_fn software_fallback);

#endif
