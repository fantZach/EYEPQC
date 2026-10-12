#include "mlkem_keccak_adapter.h"

mlkem_keccak_backend mlkem_keccakf1600_accel_or_fallback(
    const keccak_accel_io *io, uint64_t state[25], uint32_t poll_limit,
    mlkem_keccak_fallback_fn software_fallback)
{
    if (keccak_accel_permute(io, state, poll_limit) == KECCAK_ACCEL_OK)
        return MLKEM_KECCAK_HARDWARE;
    if (state == 0 || software_fallback == 0)
        return MLKEM_KECCAK_NO_FALLBACK;
    software_fallback(state);
    return MLKEM_KECCAK_SOFTWARE_FALLBACK;
}

mlkem_keccak_backend mlkem_keccakf1600_accel_or_fallback_prevalidated(
    const keccak_accel_io *io, uint64_t state[25], uint32_t poll_limit,
    mlkem_keccak_fallback_fn software_fallback)
{
    if (keccak_accel_permute_prevalidated(io, state, poll_limit) == KECCAK_ACCEL_OK)
        return MLKEM_KECCAK_HARDWARE;
    if (state == 0 || software_fallback == 0)
        return MLKEM_KECCAK_NO_FALLBACK;
    software_fallback(state);
    return MLKEM_KECCAK_SOFTWARE_FALLBACK;
}
