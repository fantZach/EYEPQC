#ifndef MVP_GCM_H
#define MVP_GCM_H
#include <stddef.h>
#include <stdint.h>
#define MVP_MAX_IMAGE 524288U
typedef int (*mvp_aes_block)(void *, const uint8_t[16], uint8_t[16]);
void mvp_zero(void *data, size_t length);
int mvp_gcm_encrypt(uint8_t *data, size_t length, const uint8_t nonce[12],
                    const uint8_t *aad, size_t aad_length, uint8_t tag[16],
                    mvp_aes_block aes, void *context);
#endif
