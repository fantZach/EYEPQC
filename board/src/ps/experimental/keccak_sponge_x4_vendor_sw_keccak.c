/* Resolve the regular (non-x4) FIPS202 calls to the independent C reference. */
#include "mlkem_sponge_backend_config.h"
#include "mlkem/src/fips202/keccakf1600.h"

void eye_mlkem_ref_keccakf1600_permute(uint64_t *state);
void eye_mlkem_ref_keccakf1600_extract_bytes(uint64_t *state,
                                             unsigned char *data,
                                             unsigned offset,
                                             unsigned length);
void eye_mlkem_ref_keccakf1600_xor_bytes(uint64_t *state,
                                          const unsigned char *data,
                                          unsigned offset,
                                          unsigned length);

void eye_mlkem_keccakf1600_permute(uint64_t *state)
{
    eye_mlkem_ref_keccakf1600_permute(state);
}

void eye_mlkem_keccakf1600_extract_bytes(uint64_t *state,
                                          unsigned char *data,
                                          unsigned offset,
                                          unsigned length)
{
    eye_mlkem_ref_keccakf1600_extract_bytes(state, data, offset, length);
}

void eye_mlkem_keccakf1600_xor_bytes(uint64_t *state,
                                      const unsigned char *data,
                                      unsigned offset,
                                      unsigned length)
{
    eye_mlkem_ref_keccakf1600_xor_bytes(state, data, offset, length);
}
