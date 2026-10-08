#ifndef EYEPQC_MLKEM_FIPS202_CUSTOM_H
#define EYEPQC_MLKEM_FIPS202_CUSTOM_H

/* Experimental build hook: preserve mlkem-native's public FIPS202 API. The
 * separately compiled vendored fips202.c implementation resolves its
 * Keccak-f symbol to mlkem_fips202_backend.c. */
#include "fips202/fips202.h"

#endif
