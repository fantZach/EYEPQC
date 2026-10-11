#include "g6_hmac_drbg.h"
#include <stdio.h>
#include <string.h>

static int from_hex(uint8_t *out, size_t capacity, const char *hex)
{
    size_t length = strlen(hex);
    if ((length & 1U) || length / 2U > capacity) return 1;
    for (size_t i = 0; i < length / 2U; ++i) {
        unsigned value;
        if (sscanf(hex + i * 2U, "%2x", &value) != 1) return 1;
        out[i] = (uint8_t)value;
    }
    return (int)(length / 2U);
}

static int test_nist_sha256_vector(void)
{
    static const char first_hex[] =
        "D67B8C1734F46FA3F763CF57C6F9F4F2DC1089BD8BC1F6F023950BFC5617635"
        "208C8501238AD7A4400DEFEE46C640B61AF77C2D1A3BFAA90EDE5D207406E5403";
    static const char second_hex[] =
        "8FDAEC20F8B421407059E3588920DA7EDA9DCE3CF8274DFA1C59C108C1D0AA9B"
        "0FA38DA5C792037C4D33CD070CA7CD0C5608DBA8B885654639DE2187B74CB263";
    struct eye_hmac_drbg state;
    uint8_t entropy[55], nonce[8], expected[64], output[64];
    for (unsigned i = 0; i < sizeof entropy; ++i) entropy[i] = (uint8_t)i;
    for (unsigned i = 0; i < sizeof nonce; ++i) nonce[i] = (uint8_t)(0x20U + i);
    if (from_hex(expected, sizeof expected, first_hex) != 64 ||
        eye_hmac_drbg_instantiate(&state, 128U, entropy, sizeof entropy,
                                  nonce, sizeof nonce, NULL, 0U) ||
        eye_hmac_drbg_generate(&state, output, sizeof output, NULL, 0U) ||
        memcmp(output, expected, sizeof output)) return 1;
    if (from_hex(expected, sizeof expected, second_hex) != 64 ||
        eye_hmac_drbg_generate(&state, output, sizeof output, NULL, 0U) ||
        memcmp(output, expected, sizeof output)) return 2;
    eye_hmac_drbg_uninstantiate(&state);
    for (unsigned i = 0; i < sizeof state; ++i)
        if (((const uint8_t *)&state)[i]) return 3;
    return 0;
}

static int test_bounds_and_reseed_gate(void)
{
    struct eye_hmac_drbg state, snapshot;
    uint8_t entropy[32] = {0x31U}, nonce[16] = {0x72U};
    uint8_t output[32];
    memset(&state, 0, sizeof state);
    memset(output, 0xa5, sizeof output);
    if (eye_hmac_drbg_generate(&state, output, sizeof output, NULL, 0U) !=
        EYE_HMAC_DRBG_STATE) return 1;
    for (unsigned i = 0; i < sizeof output; ++i)
        if (output[i]) return 2;
    if (eye_hmac_drbg_instantiate(&state, 256U, entropy, sizeof entropy - 1U,
                                  nonce, sizeof nonce, NULL, 0U) !=
        EYE_HMAC_DRBG_INPUT) return 3;
    if (eye_hmac_drbg_instantiate(&state, 256U, entropy, sizeof entropy,
                                  nonce, sizeof nonce, NULL, 0U)) return 4;
    snapshot = state;
    if (eye_hmac_drbg_generate(&state, output, sizeof output, NULL,
                               EYE_HMAC_DRBG_MAX_ADDITIONAL_BYTES + 1U) !=
        EYE_HMAC_DRBG_INPUT || memcmp(&snapshot, &state, sizeof state)) return 5;
    if (eye_hmac_drbg_reseed(&state, entropy, sizeof entropy - 1U, NULL, 0U) !=
        EYE_HMAC_DRBG_INPUT || memcmp(&snapshot, &state, sizeof state)) return 6;
    state.reseed_counter = EYE_HMAC_DRBG_RESEED_INTERVAL + 1U;
    memset(output, 0xa5, sizeof output);
    if (eye_hmac_drbg_generate(&state, output, sizeof output, NULL, 0U) !=
        EYE_HMAC_DRBG_RESEED_REQUIRED) return 7;
    for (unsigned i = 0; i < sizeof output; ++i)
        if (output[i]) return 8;
    if (eye_hmac_drbg_reseed(&state, entropy, sizeof entropy, NULL, 0U) ||
        eye_hmac_drbg_needs_reseed(&state) ||
        eye_hmac_drbg_generate(&state, output, sizeof output, NULL, 0U)) return 9;
    return 0;
}

int main(void)
{
    int status = test_nist_sha256_vector();
    if (!status) status = test_bounds_and_reseed_gate();
    if (status) {
        fprintf(stderr, "G6_HMAC_DRBG_FAIL=%d\n", status);
        return 1;
    }
    puts("G6_HMAC_DRBG_PASS nist_sha256=2 reseed_gate=1 bounds=1");
    return 0;
}
