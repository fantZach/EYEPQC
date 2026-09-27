/* SP 800-38D, 96-bit IV / full tag. AES is supplied by the actual PL driver. */
#include "mvp_gcm.h"
#include <string.h>

void mvp_zero(void *data, size_t length)
{
    volatile uint8_t *p = data;
    while (length--) *p++ = 0;
}

static void ghash_block(uint8_t state[16], const uint8_t h[16], const uint8_t block[16])
{
    uint8_t x[16], v[16], z[16] = {0};
    unsigned int i, j;
    for (i = 0; i < 16; i++) { x[i] = state[i] ^ block[i]; v[i] = h[i]; }
    /* Fixed work and no secret-dependent branches/table addresses. */
    for (i = 0; i < 128; i++) {
        uint8_t mask = (uint8_t)(0U - ((x[i / 8] >> (7U - i % 8)) & 1U));
        uint8_t reduce = (uint8_t)(0U - (v[15] & 1U));
        for (j = 0; j < 16; j++) z[j] ^= v[j] & mask;
        for (j = 15; j > 0; j--) v[j] = (uint8_t)((v[j] >> 1) | (v[j - 1] << 7));
        v[0] = (uint8_t)((v[0] >> 1) ^ (0xe1U & reduce));
    }
    memcpy(state, z, 16);
    mvp_zero(x, 16); mvp_zero(v, 16); mvp_zero(z, 16);
}

static void put64(uint8_t *p, uint64_t value)
{
    unsigned int i;
    for (i = 0; i < 8; i++) p[7 - i] = (uint8_t)(value >> (i * 8));
}

int mvp_gcm_encrypt(uint8_t *data, size_t length, const uint8_t nonce[12],
                    const uint8_t *aad, size_t aad_length, uint8_t tag[16],
                    mvp_aes_block aes, void *context)
{
    uint8_t h[16], mask[16], state[16] = {0}, counter[16] = {0};
    uint8_t stream[16], block[16];
    uint32_t count = 1;
    size_t offset, n, i;
    int error = 1;
    if ((!data && length) || !nonce || (!aad && aad_length) || !tag || !aes ||
        length > MVP_MAX_IMAGE || aad_length > 64) return 2;
    memset(tag, 0, 16);
    if (aes(context, counter, h)) goto done;
    memcpy(counter, nonce, 12); counter[15] = 1;
    if (aes(context, counter, mask)) goto done;
    for (offset = 0; offset < aad_length; offset += n) {
        n = aad_length - offset; if (n > 16) n = 16;
        memset(block, 0, 16); memcpy(block, aad + offset, n);
        ghash_block(state, h, block);
    }
    // ponytail: software GHASH/MMIO for <=512 KiB; M07/M08 move it to PL for video.
    for (offset = 0; offset < length; offset += n) {
        n = length - offset; if (n > 16) n = 16;
        count++;
        for (i = 0; i < 4; i++) counter[15 - i] = (uint8_t)(count >> (i * 8));
        if (aes(context, counter, stream)) goto done;
        memset(block, 0, 16);
        for (i = 0; i < n; i++) { data[offset + i] ^= stream[i]; block[i] = data[offset + i]; }
        ghash_block(state, h, block);
    }
    put64(block, (uint64_t)aad_length * 8); put64(block + 8, (uint64_t)length * 8);
    ghash_block(state, h, block);
    for (i = 0; i < 16; i++) tag[i] = state[i] ^ mask[i];
    error = 0;
done:
    mvp_zero(h, 16); mvp_zero(mask, 16); mvp_zero(state, 16);
    mvp_zero(counter, 16); mvp_zero(stream, 16); mvp_zero(block, 16);
    if (error && length) mvp_zero(data, length);
    return error;
}
