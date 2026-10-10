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
static int active_identity_validated;
static mlkem_fips202_backend_stats stats;

static void software_permute(uint64_t state[25])
{
    eye_mlkem_ref_keccakf1600_permute(state);
}

int mlkem_fips202_backend_configure(const keccak_accel_io *io,
                                    uint32_t poll_limit)
{
    if (io != NULL) active_io = *io;
    else memset(&active_io, 0, sizeof active_io);
    active_poll_limit = poll_limit;
    active_identity_validated = 0;
    if (active_io.activation_cookie == KECCAK_ACCEL_EXPERIMENTAL_ENABLE &&
        active_io.read32 != 0 && active_io.write32 != 0 && active_poll_limit != 0) {
        uint32_t id = active_io.read32(active_io.opaque, KECCAK_ACCEL_ID_OFFSET);
        uint32_t version = active_io.read32(active_io.opaque, KECCAK_ACCEL_VERSION_OFFSET);
        active_identity_validated =
            id == KECCAK_ACCEL_ID_VALUE && version == KECCAK_ACCEL_VERSION_VALUE;
    }
    return active_identity_validated;
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
    if (active_identity_validated)
        result = mlkem_keccakf1600_accel_or_fallback_prevalidated(
            &active_io, state, active_poll_limit, software_permute);
    else {
        software_permute(state);
        result = MLKEM_KECCAK_SOFTWARE_FALLBACK;
    }
    if (result == MLKEM_KECCAK_HARDWARE) ++stats.hardware_successes;
    else if (result == MLKEM_KECCAK_SOFTWARE_FALLBACK) ++stats.software_fallbacks;
}
