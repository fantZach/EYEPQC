#ifndef EYEPQC_KECCAK_ACCEL_H
#define EYEPQC_KECCAK_ACCEL_H

#include <stdint.h>

#define KECCAK_ACCEL_CTRL_OFFSET       0x000u
#define KECCAK_ACCEL_STATUS_OFFSET     0x004u
#define KECCAK_ACCEL_WATCHDOG_OFFSET   0x008u
#define KECCAK_ACCEL_ID_OFFSET         0x00cu
#define KECCAK_ACCEL_VERSION_OFFSET    0x010u
#define KECCAK_ACCEL_STATE_OFFSET      0x100u
#define KECCAK_ACCEL_RESULT_OFFSET     0x200u
#define KECCAK_ACCEL_CTRL_START        (1u << 0)
#define KECCAK_ACCEL_CTRL_CLEAR        (1u << 1)
#define KECCAK_ACCEL_STATUS_BUSY       (1u << 0)
#define KECCAK_ACCEL_STATUS_DONE       (1u << 1)
#define KECCAK_ACCEL_STATUS_ERROR      (1u << 2)
#define KECCAK_ACCEL_STATUS_TIMEOUT    (1u << 3)
#define KECCAK_ACCEL_ID_VALUE          0x4b434831u /* KCH1 */
#define KECCAK_ACCEL_VERSION_VALUE     0x00010000u
#define KECCAK_ACCEL_EXPERIMENTAL_ENABLE 0x4b434b45u /* explicit XSA opt-in */

typedef uint32_t (*keccak_accel_read32_fn)(void *opaque, uint32_t offset);
typedef void (*keccak_accel_write32_fn)(void *opaque, uint32_t offset, uint32_t value);

typedef struct {
    void *opaque;
    keccak_accel_read32_fn read32;
    keccak_accel_write32_fn write32;
    /* Must be explicitly set only after the caller validates its XSA/address map. */
    uint32_t activation_cookie;
} keccak_accel_io;

typedef enum {
    KECCAK_ACCEL_OK = 0,
    KECCAK_ACCEL_INVALID = -1,
    KECCAK_ACCEL_HW_ERROR = -2,
    KECCAK_ACCEL_TIMEOUT = -3
} keccak_accel_result;

/* poll_limit bounds CPU wait even if the peripheral watchdog is disabled. */
keccak_accel_result keccak_accel_permute(const keccak_accel_io *io,
                                         uint64_t state[25],
                                         uint32_t poll_limit);

/* Fast path for a hardware context that has just been configured and had its
 * ID/version checked. Keep keccak_accel_permute() as the guarded public default. */
keccak_accel_result keccak_accel_permute_prevalidated(const keccak_accel_io *io,
                                                      uint64_t state[25],
                                                      uint32_t poll_limit);

/* Adapt a platform's MMIO base pointer to the callback-based testable API. */
typedef struct {
    volatile uint32_t *base;
} keccak_accel_mmio;
uint32_t keccak_accel_mmio_read(void *opaque, uint32_t offset);
void keccak_accel_mmio_write(void *opaque, uint32_t offset, uint32_t value);

#endif
