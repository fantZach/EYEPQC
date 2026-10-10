#ifndef EYEPQC_KECCAK_SPONGE_X4_H
#define EYEPQC_KECCAK_SPONGE_X4_H

#include "keccak_accel.h"

#define KECCAK_SX4_CTRL_OFFSET       0x000u
#define KECCAK_SX4_STATUS_OFFSET     0x004u
#define KECCAK_SX4_WDOG_OFFSET       0x008u
#define KECCAK_SX4_ID_OFFSET         0x00cu
#define KECCAK_SX4_VERSION_OFFSET    0x010u
#define KECCAK_SX4_INLEN_OFFSET      0x020u
#define KECCAK_SX4_INPUT_OFFSET      0x100u
#define KECCAK_SX4_OUTPUT_OFFSET     0x400u
#define KECCAK_SX4_ID_VALUE          0x4b583431u /* KX41 */
#define KECCAK_SX4_VERSION_VALUE     0x00010000u
#define KECCAK_SX4_CTRL_ABSORB        1u
#define KECCAK_SX4_CTRL_SQUEEZE       2u
#define KECCAK_SX4_CTRL_CLEAR         4u
#define KECCAK_SX4_STATUS_BUSY        (1u << 0)
#define KECCAK_SX4_STATUS_DONE        (1u << 1)
#define KECCAK_SX4_STATUS_ERROR       (1u << 2)
#define KECCAK_SX4_STATUS_TIMEOUT     (1u << 3)
#define KECCAK_SX4_STATUS_CONTEXT     (1u << 4)
#define KECCAK_SX4_MAX_INPUT_BYTES    169u
#define KECCAK_SX4_RATE_BYTES         168u
#define KECCAK_SX4_MAX_BLOCKS         8u

typedef struct {
    uint32_t absorb_calls;
    uint32_t hardware_absorbs;
    uint32_t hardware_squeeze_blocks;
    uint32_t software_fallbacks;
    uint32_t timeout_fallbacks;
    uint32_t error_fallbacks;
} keccak_sponge_x4_stats;

int keccak_sponge_x4_configure(const keccak_accel_io *io,
                               uint32_t poll_limit);
void keccak_sponge_x4_reset_stats(void);
keccak_sponge_x4_stats keccak_sponge_x4_get_stats(void);

#endif
