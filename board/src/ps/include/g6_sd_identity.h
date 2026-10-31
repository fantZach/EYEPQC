#ifndef EYEPQC_G6_SD_IDENTITY_H
#define EYEPQC_G6_SD_IDENTITY_H
#include <stddef.h>
#include <stdint.h>
int g6_sd_identity_init(uint8_t private_key[1632]);
int g6_sd_identity_random(uint8_t *out, size_t length, const uint8_t additional[32]);
void g6_sd_identity_shutdown(void);
#endif
