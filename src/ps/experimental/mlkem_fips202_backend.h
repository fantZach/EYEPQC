#ifndef EYEPQC_MLKEM_FIPS202_BACKEND_H
#define EYEPQC_MLKEM_FIPS202_BACKEND_H

#include "keccak_accel.h"

typedef struct {
    uint32_t dispatch_calls;
    uint32_t hardware_successes;
    uint32_t software_fallbacks;
} mlkem_fips202_backend_stats;

void mlkem_fips202_backend_configure(const keccak_accel_io *io,
                                     uint32_t poll_limit);
void mlkem_fips202_backend_reset_stats(void);
mlkem_fips202_backend_stats mlkem_fips202_backend_get_stats(void);

#endif
