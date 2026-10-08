#include "keccak_accel.h"

#if defined(__arm__) || defined(__aarch64__)
#define KECCAK_ACCEL_BARRIER() __asm__ volatile("dmb sy" ::: "memory")
#else
#define KECCAK_ACCEL_BARRIER() __asm__ volatile("" ::: "memory")
#endif

static uint32_t lane_word(const uint64_t *state, uint32_t word)
{
    const uint32_t lane = word >> 1;
    return (word & 1u) ? (uint32_t)(state[lane] >> 32) : (uint32_t)state[lane];
}

static void set_lane_word(uint64_t *state, uint32_t word, uint32_t value)
{
    const uint32_t lane = word >> 1;
    if (word & 1u)
        state[lane] = (state[lane] & UINT64_C(0x00000000ffffffff)) | ((uint64_t)value << 32);
    else
        state[lane] = (state[lane] & UINT64_C(0xffffffff00000000)) | value;
}

static void clear_device(const keccak_accel_io *io)
{
    io->write32(io->opaque, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_CLEAR);
}

static void secure_zero_state(uint64_t state[25])
{
    volatile uint64_t *p = (volatile uint64_t *)state;
    uint32_t i;
    for (i = 0; i < 25; ++i) p[i] = 0;
}

keccak_accel_result keccak_accel_permute(const keccak_accel_io *io,
                                         uint64_t state[25],
                                         uint32_t poll_limit)
{
    uint32_t word, poll, status;
    uint64_t result[25] = {0};

    // Default/off is safe: do not probe an unmapped peripheral. The integrator
    // opts in only after matching the experimental XSA and assigned base address.
    if (io == 0 || io->activation_cookie != KECCAK_ACCEL_EXPERIMENTAL_ENABLE ||
        io->read32 == 0 || io->write32 == 0 || state == 0 || poll_limit == 0)
        return KECCAK_ACCEL_INVALID;
    if (io->read32(io->opaque, KECCAK_ACCEL_ID_OFFSET) != KECCAK_ACCEL_ID_VALUE ||
        io->read32(io->opaque, KECCAK_ACCEL_VERSION_OFFSET) != KECCAK_ACCEL_VERSION_VALUE)
        return KECCAK_ACCEL_INVALID;

    clear_device(io);
    for (word = 0; word < 50; ++word)
        io->write32(io->opaque, KECCAK_ACCEL_STATE_OFFSET + 4u * word,
                    lane_word(state, word));
    KECCAK_ACCEL_BARRIER();
    io->write32(io->opaque, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_START);

    for (poll = 0; poll < poll_limit; ++poll) {
        status = io->read32(io->opaque, KECCAK_ACCEL_STATUS_OFFSET);
        if (status & (KECCAK_ACCEL_STATUS_ERROR | KECCAK_ACCEL_STATUS_TIMEOUT)) {
            clear_device(io);
            return (status & KECCAK_ACCEL_STATUS_TIMEOUT) ?
                   KECCAK_ACCEL_TIMEOUT : KECCAK_ACCEL_HW_ERROR;
        }
        if ((status & KECCAK_ACCEL_STATUS_DONE) && !(status & KECCAK_ACCEL_STATUS_BUSY)) {
            KECCAK_ACCEL_BARRIER();
            for (word = 0; word < 50; ++word)
                set_lane_word(result, word,
                    io->read32(io->opaque, KECCAK_ACCEL_RESULT_OFFSET + 4u * word));
            for (word = 0; word < 25; ++word) state[word] = result[word];
            clear_device(io);
            secure_zero_state(result);
            return KECCAK_ACCEL_OK;
        }
    }
    clear_device(io);
    return KECCAK_ACCEL_TIMEOUT;
}

uint32_t keccak_accel_mmio_read(void *opaque, uint32_t offset)
{
    const keccak_accel_mmio *mmio = (const keccak_accel_mmio *)opaque;
    return mmio->base[offset >> 2];
}

void keccak_accel_mmio_write(void *opaque, uint32_t offset, uint32_t value)
{
    keccak_accel_mmio *mmio = (keccak_accel_mmio *)opaque;
    mmio->base[offset >> 2] = value;
}
