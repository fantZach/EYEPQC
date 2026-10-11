#ifndef EYEPQC_G6_PRODUCTION_PROVIDER_H
#define EYEPQC_G6_PRODUCTION_PROVIDER_H

#include <stdint.h>

/*
 * Platform integration contract for the opt-in G6 production profile.
 * The project intentionally supplies no implementation: a production link
 * without a reviewed provider must fail with unresolved symbols.
 *
 * security_init must fail unless the selected key service is available and
 * the entropy/DRBG service has passed its startup checks. random_bytes must
 * return fresh cryptographic random bytes and fail closed on health/reseed
 * errors. read_mlkem512_private_key returns the provisioned device key into
 * caller RAM; G6 validates, pins its public-key identity, and wipes each copy.
 * security_shutdown must be idempotent and safe after a failed/partial init.
 * Provider implementations must document their actual storage and entropy
 * properties. This interface alone does not establish either property.
 */
int g6_production_security_init(void);
int g6_production_read_mlkem512_private_key(uint8_t out[1632]);
int g6_production_random_bytes(uint8_t out[32]);
void g6_production_security_shutdown(void);

#endif
