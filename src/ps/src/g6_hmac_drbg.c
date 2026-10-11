#include "g6_hmac_drbg.h"
#include "session.h"
#include <string.h>

#define SEED_MATERIAL_MAX (EYE_HMAC_DRBG_MAX_ENTROPY_BYTES + \
                           EYE_HMAC_DRBG_MAX_NONCE_BYTES + \
                           EYE_HMAC_DRBG_MAX_PERSONALIZATION_BYTES)
#define UPDATE_INPUT_MAX (32U + 1U + SEED_MATERIAL_MAX)

static void wipe(void *memory, size_t length)
{
    volatile uint8_t *p = (volatile uint8_t *)memory;
    while (length--) *p++ = 0U;
}

static int valid_input(const uint8_t *data, size_t length, size_t maximum,
                       int allow_empty)
{
    return length <= maximum && (length == 0U ? allow_empty : data != NULL);
}

static int hmac_update(struct eye_hmac_drbg *state,
                       const uint8_t *provided, size_t provided_length)
{
    uint8_t input[UPDATE_INPUT_MAX];
    int status = EYE_HMAC_DRBG_CRYPTO;
    size_t length = 33U + provided_length;

    memcpy(input, state->value, 32U);
    input[32] = 0U;
    if (provided_length) memcpy(input + 33U, provided, provided_length);
    if (eye_hmac_sha256(state->key, state->key, sizeof state->key,
                        input, length)) goto done;
    if (eye_hmac_sha256(state->value, state->key, sizeof state->key,
                        state->value, sizeof state->value)) goto done;
    if (provided_length) {
        memcpy(input, state->value, 32U);
        input[32] = 1U;
        memcpy(input + 33U, provided, provided_length);
        if (eye_hmac_sha256(state->key, state->key, sizeof state->key,
                            input, length)) goto done;
        if (eye_hmac_sha256(state->value, state->key, sizeof state->key,
                            state->value, sizeof state->value)) goto done;
    }
    status = EYE_HMAC_DRBG_OK;
done:
    wipe(input, sizeof input);
    return status;
}

int eye_hmac_drbg_instantiate(struct eye_hmac_drbg *state,
                              uint16_t security_strength_bits,
                              const uint8_t *entropy, size_t entropy_length,
                              const uint8_t *nonce, size_t nonce_length,
                              const uint8_t *personalization,
                              size_t personalization_length)
{
    uint8_t seed[SEED_MATERIAL_MAX];
    size_t seed_length;
    int status;

    if (!state || security_strength_bits < EYE_HMAC_DRBG_MIN_STRENGTH_BITS ||
        security_strength_bits > EYE_HMAC_DRBG_MAX_STRENGTH_BITS ||
        (security_strength_bits & 7U) ||
        !valid_input(entropy, entropy_length,
                     EYE_HMAC_DRBG_MAX_ENTROPY_BYTES, 0) ||
        !valid_input(nonce, nonce_length, EYE_HMAC_DRBG_MAX_NONCE_BYTES, 0) ||
        entropy_length < (size_t)(security_strength_bits / 8U) ||
        nonce_length * 16U < (size_t)security_strength_bits ||
        !valid_input(personalization, personalization_length,
                     EYE_HMAC_DRBG_MAX_PERSONALIZATION_BYTES, 1))
        return EYE_HMAC_DRBG_INPUT;

    seed_length = entropy_length + nonce_length + personalization_length;
    memcpy(seed, entropy, entropy_length);
    memcpy(seed + entropy_length, nonce, nonce_length);
    if (personalization_length)
        memcpy(seed + entropy_length + nonce_length, personalization,
               personalization_length);
    wipe(state, sizeof *state);
    memset(state->value, 0x01, sizeof state->value);
    status = hmac_update(state, seed, seed_length);
    wipe(seed, sizeof seed);
    if (status) {
        wipe(state, sizeof *state);
        return status;
    }
    state->reseed_counter = 1U;
    state->instantiated = 1U;
    state->security_strength_bits = security_strength_bits;
    return EYE_HMAC_DRBG_OK;
}

int eye_hmac_drbg_reseed(struct eye_hmac_drbg *state,
                         const uint8_t *entropy, size_t entropy_length,
                         const uint8_t *additional, size_t additional_length)
{
    uint8_t seed[EYE_HMAC_DRBG_MAX_ENTROPY_BYTES +
                 EYE_HMAC_DRBG_MAX_ADDITIONAL_BYTES];
    size_t seed_length;
    int status;

    if (!state || !valid_input(entropy, entropy_length,
                               EYE_HMAC_DRBG_MAX_ENTROPY_BYTES, 0) ||
        !valid_input(additional, additional_length,
                     EYE_HMAC_DRBG_MAX_ADDITIONAL_BYTES, 1))
        return EYE_HMAC_DRBG_INPUT;
    if (!state->instantiated) return EYE_HMAC_DRBG_STATE;
    if (state->security_strength_bits < EYE_HMAC_DRBG_MIN_STRENGTH_BITS ||
        state->security_strength_bits > EYE_HMAC_DRBG_MAX_STRENGTH_BITS ||
        entropy_length < (size_t)(state->security_strength_bits / 8U))
        return EYE_HMAC_DRBG_INPUT;

    seed_length = entropy_length + additional_length;
    memcpy(seed, entropy, entropy_length);
    if (additional_length)
        memcpy(seed + entropy_length, additional, additional_length);
    status = hmac_update(state, seed, seed_length);
    wipe(seed, sizeof seed);
    if (status) {
        wipe(state, sizeof *state);
        return status;
    }
    state->reseed_counter = 1U;
    return EYE_HMAC_DRBG_OK;
}

int eye_hmac_drbg_generate(struct eye_hmac_drbg *state, uint8_t *output,
                           size_t output_length, const uint8_t *additional,
                           size_t additional_length)
{
    uint8_t block[32];
    size_t offset = 0U;
    int status = EYE_HMAC_DRBG_CRYPTO;

    if (output && output_length <= EYE_HMAC_DRBG_MAX_REQUEST_BYTES)
        wipe(output, output_length);
    if (!state || !output || output_length == 0U ||
        output_length > EYE_HMAC_DRBG_MAX_REQUEST_BYTES ||
        !valid_input(additional, additional_length,
                     EYE_HMAC_DRBG_MAX_ADDITIONAL_BYTES, 1))
        return EYE_HMAC_DRBG_INPUT;
    if (!state->instantiated) return EYE_HMAC_DRBG_STATE;
    if (state->security_strength_bits < EYE_HMAC_DRBG_MIN_STRENGTH_BITS ||
        state->security_strength_bits > EYE_HMAC_DRBG_MAX_STRENGTH_BITS)
        return EYE_HMAC_DRBG_STATE;
    if (eye_hmac_drbg_needs_reseed(state))
        return EYE_HMAC_DRBG_RESEED_REQUIRED;

    if (additional_length && hmac_update(state, additional, additional_length))
        goto fail;
    while (offset < output_length) {
        size_t count = output_length - offset;
        if (eye_hmac_sha256(block, state->key, sizeof state->key,
                            state->value, sizeof state->value)) goto fail;
        memcpy(state->value, block, sizeof state->value);
        if (count > sizeof block) count = sizeof block;
        memcpy(output + offset, block, count);
        offset += count;
    }
    if (hmac_update(state, additional, additional_length)) goto fail;
    ++state->reseed_counter;
    wipe(block, sizeof block);
    return EYE_HMAC_DRBG_OK;

fail:
    wipe(block, sizeof block);
    wipe(output, output_length);
    wipe(state, sizeof *state);
    return status;
}

int eye_hmac_drbg_needs_reseed(const struct eye_hmac_drbg *state)
{
    return !state || !state->instantiated ||
           state->security_strength_bits < EYE_HMAC_DRBG_MIN_STRENGTH_BITS ||
           state->security_strength_bits > EYE_HMAC_DRBG_MAX_STRENGTH_BITS ||
           state->reseed_counter > EYE_HMAC_DRBG_RESEED_INTERVAL;
}

void eye_hmac_drbg_uninstantiate(struct eye_hmac_drbg *state)
{
    if (state) wipe(state, sizeof *state);
}
