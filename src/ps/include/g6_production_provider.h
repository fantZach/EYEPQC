#ifndef EYEPQC_G6_PRODUCTION_PROVIDER_H
#define EYEPQC_G6_PRODUCTION_PROVIDER_H

#include <stdint.h>

/*
 * Platform integration contract for the opt-in G6 production profile.
 * The project intentionally supplies no implementation: a production link
 * without a reviewed provider must fail with unresolved symbols.
 * Zynq-7000 has no built-in silicon RNG for application-layer session keys.
 * A provider must use an evaluated PL entropy source or external source;
 * timer jitter or XADC measurements alone are not an entropy-source claim.
 * A PL source also requires an authenticated boot chain for its bitstream.
 *
 * security_init must fail unless the selected key service and entropy-source
 * health checks pass. entropy_bytes must provide 48 bytes at instantiation:
 * at least 32 bytes of entropy_input followed by a fresh 16-byte nonce; at
 * reseed the caller also requests 48 bytes, using the first 32 as entropy_input
 * and the remainder as additional input. The provider must fail closed on
 * source-health errors. The firmware runs its own HMAC_DRBG-SHA-256 and
 * enforces a 1024-request reseed interval.
 * read_mlkem512_private_key returns the provisioned device key into
 * caller RAM; G6 validates, pins its public-key identity, and wipes each copy.
 * security_shutdown must be idempotent and safe after a failed/partial init.
 * Provider implementations must document their actual storage and entropy
 * properties. This interface alone does not establish either property.
 */
int g6_production_security_init(void);
int g6_production_read_mlkem512_private_key(uint8_t out[1632]);
int g6_production_entropy_bytes(uint8_t *out, uint32_t length);
void g6_production_security_shutdown(void);

#endif
