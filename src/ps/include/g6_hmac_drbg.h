#ifndef EYEPQC_G6_HMAC_DRBG_H
#define EYEPQC_G6_HMAC_DRBG_H

#include <stddef.h>
#include <stdint.h>

#define EYE_HMAC_DRBG_MAX_ENTROPY_BYTES 64U
#define EYE_HMAC_DRBG_MAX_NONCE_BYTES 32U
#define EYE_HMAC_DRBG_MAX_PERSONALIZATION_BYTES 256U
#define EYE_HMAC_DRBG_MAX_ADDITIONAL_BYTES 256U
#define EYE_HMAC_DRBG_MAX_REQUEST_BYTES 65536U
#define EYE_HMAC_DRBG_RESEED_INTERVAL 1024U
#define EYE_HMAC_DRBG_MIN_STRENGTH_BITS 128U
#define EYE_HMAC_DRBG_MAX_STRENGTH_BITS 256U

enum eye_hmac_drbg_result {
    EYE_HMAC_DRBG_OK = 0,
    EYE_HMAC_DRBG_INPUT = -1,
    EYE_HMAC_DRBG_STATE = -2,
    EYE_HMAC_DRBG_RESEED_REQUIRED = -3,
    EYE_HMAC_DRBG_CRYPTO = -4
};

struct eye_hmac_drbg {
    uint8_t key[32];
    uint8_t value[32];
    uint32_t reseed_counter;
    uint8_t instantiated;
    uint16_t security_strength_bits;
};

/* HMAC_DRBG-SHA-256, SP 800-90A Rev. 1, section 10.1.2. */
/* Invalid instantiate/reseed/generate inputs wipe the supplied state. A
 * RESEED_REQUIRED result is a normal gate and preserves state for reseeding. */
int eye_hmac_drbg_instantiate(struct eye_hmac_drbg *state,
                              uint16_t security_strength_bits,
                              const uint8_t *entropy, size_t entropy_length,
                              const uint8_t *nonce, size_t nonce_length,
                              const uint8_t *personalization,
                              size_t personalization_length);
int eye_hmac_drbg_reseed(struct eye_hmac_drbg *state,
                         const uint8_t *entropy, size_t entropy_length,
                         const uint8_t *additional, size_t additional_length);
int eye_hmac_drbg_generate(struct eye_hmac_drbg *state, uint8_t *output,
                           size_t output_length, const uint8_t *additional,
                           size_t additional_length);
int eye_hmac_drbg_needs_reseed(const struct eye_hmac_drbg *state);
void eye_hmac_drbg_uninstantiate(struct eye_hmac_drbg *state);

#endif
