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
 * read_mlkem512_public_key returns only the validated public key for the
 * provider's protected key object. The private key must remain behind the
 * provider boundary and must never be returned to the G6 application.
 * mlkem512_decapsulate must compare the protected key object's public-key hash
 * to expected_public_key_hash in constant time, and perform that check and
 * decapsulation atomically with respect to key rotation. It returns only the
 * 32-byte shared secret; on every error it must clear the output. The caller
 * independently clears that output after use.
 * security_shutdown must be idempotent and safe after a failed/partial init.
 * Provider implementations must document their actual storage and entropy
 * properties. This interface alone does not establish either property.
 */
int g6_production_security_init(void);
int g6_production_read_mlkem512_public_key(uint8_t out[800]);
int g6_production_mlkem512_decapsulate(uint8_t shared[32],
                                      const uint8_t ciphertext[768],
                                      const uint8_t expected_public_key_hash[32]);
int g6_production_entropy_bytes(uint8_t *out, uint32_t length);
void g6_production_security_shutdown(void);

#endif
