#ifndef EYEPQC_KECCAK_SPONGE_X4_HOSTMOCK_H
#define EYEPQC_KECCAK_SPONGE_X4_HOSTMOCK_H

#include "keccak_accel.h"

#include <stdint.h>

void sx4_hostmock_reset(uint32_t id, uint32_t version);
void *sx4_hostmock_opaque(void);
void sx4_hostmock_set_failure(uint32_t command_number, int timeout);
uint32_t sx4_hostmock_launches(void);
uint32_t sx4_hostmock_state_writes(void);
uint32_t sx4_hostmock_command_number(void);
uint32_t sx4_hostmock_read32(void *opaque, uint32_t offset);
void sx4_hostmock_write32(void *opaque, uint32_t offset, uint32_t value);

#endif
