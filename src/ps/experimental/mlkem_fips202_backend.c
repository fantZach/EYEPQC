#include "mlkem_fips202_backend.h"
#include "mlkem_keccak_adapter.h"

#include <string.h>

/* The reference implementation is the unmodified vendored keccakf1600.c,
 * compiled in this experiment with a separate namespace. */
void eye_mlkem_ref_keccakf1600_permute(uint64_t state[25]);
void eye_mlkem_ref_keccakf1600_extract_bytes(uint64_t state[25],
                                              unsigned char *data,
                                              unsigned offset,
                                              unsigned length);
void eye_mlkem_ref_keccakf1600_xor_bytes(uint64_t state[25],
                                          const unsigned char *data,
                                          unsigned offset,
                                          unsigned length);

static keccak_accel_io active_io;
static uint32_t active_poll_limit;
static mlkem_fips202_backend_stats stats;

static void software_permute(uint64_t state[25])
{
    eye_mlkem_ref_keccakf1600_permute(state);
}

void mlkem_fips202_backend_configure(const keccak_accel_io *io,
                                     uint32_t poll_limit)
{
    if (io != NULL) active_io = *io;
    else memset(&active_io, 0, sizeof active_io);
    active_poll_limit = poll_limit;
}

void mlkem_fips202_backend_reset_stats(void)
{
    memset(&stats, 0, sizeof stats);
}

mlkem_fips202_backend_stats mlkem_fips202_backend_get_stats(void)
{
    return stats;
}

/* These three symbols satisfy the exact namespace expected by the separately
 * compiled vendored fips202.c. Byte extraction/XOR remain its original C
 * implementation; only the permutation dispatches through the PS adapter. */
void eye_mlkem_keccakf1600_extract_bytes(uint64_t state[25],
                                         unsigned char *data,
                                         unsigned offset, unsigned length)
{
    eye_mlkem_ref_keccakf1600_extract_bytes(state, data, offset, length);
}

void eye_mlkem_keccakf1600_xor_bytes(uint64_t state[25],
                                     const unsigned char *data,
                                     unsigned offset, unsigned length)
{
    eye_mlkem_ref_keccakf1600_xor_bytes(state, data, offset, length);
}

void eye_mlkem_keccakf1600_permute(uint64_t state[25])
{
    mlkem_keccak_backend result;
    ++stats.dispatch_calls;
    result = mlkem_keccakf1600_accel_or_fallback(
        &active_io, state, active_poll_limit, software_permute);
    if (result == MLKEM_KECCAK_HARDWARE) ++stats.hardware_successes;
    else if (result == MLKEM_KECCAK_SOFTWARE_FALLBACK) ++stats.software_fallbacks;
}
