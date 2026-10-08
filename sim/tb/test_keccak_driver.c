#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "keccak_accel.h"
#include "mlkem_keccak_adapter.h"

#define MOCK_WORDS (0x300u / 4u)
typedef struct {
    uint32_t regs[MOCK_WORDS];
    unsigned polls_left;
    unsigned clear_count;
    unsigned starts;
    unsigned state_writes;
    unsigned reads;
    int never_complete;
    int inject_error;
    uint32_t id_value;
    uint32_t version_value;
} mock_device;

static void clear_regs(mock_device *m)
{
    unsigned i;
    for (i = KECCAK_ACCEL_STATE_OFFSET/4; i < (KECCAK_ACCEL_STATE_OFFSET+200)/4; ++i)
        m->regs[i] = 0;
    for (i = KECCAK_ACCEL_RESULT_OFFSET/4; i < (KECCAK_ACCEL_RESULT_OFFSET+200)/4; ++i)
        m->regs[i] = 0;
    m->regs[KECCAK_ACCEL_STATUS_OFFSET/4] = 0;
    ++m->clear_count;
}

static uint32_t mock_read(void *opaque, uint32_t offset)
{
    mock_device *m = (mock_device *)opaque;
    unsigned i;
    ++m->reads;
    if (offset == KECCAK_ACCEL_ID_OFFSET)
        return m->id_value ? m->id_value : KECCAK_ACCEL_ID_VALUE;
    if (offset == KECCAK_ACCEL_VERSION_OFFSET)
        return m->version_value ? m->version_value : KECCAK_ACCEL_VERSION_VALUE;
    if (offset == KECCAK_ACCEL_STATUS_OFFSET &&
        (m->regs[offset/4] & KECCAK_ACCEL_STATUS_BUSY)) {
        if (m->inject_error) return KECCAK_ACCEL_STATUS_ERROR;
        if (m->never_complete) return KECCAK_ACCEL_STATUS_BUSY;
        if (m->polls_left != 0) {
            --m->polls_left;
            return KECCAK_ACCEL_STATUS_BUSY;
        }
        for (i = 0; i < 50; ++i)
            m->regs[KECCAK_ACCEL_RESULT_OFFSET/4+i] =
                m->regs[KECCAK_ACCEL_STATE_OFFSET/4+i] ^ (0xa5a50000u + i);
        m->regs[KECCAK_ACCEL_STATUS_OFFSET/4] = KECCAK_ACCEL_STATUS_DONE;
        return KECCAK_ACCEL_STATUS_DONE;
    }
    return m->regs[offset/4];
}

static void mock_write(void *opaque, uint32_t offset, uint32_t value)
{
    mock_device *m = (mock_device *)opaque;
    if (offset == KECCAK_ACCEL_CTRL_OFFSET && value == KECCAK_ACCEL_CTRL_CLEAR) {
        clear_regs(m);
    } else if (offset == KECCAK_ACCEL_CTRL_OFFSET && value == KECCAK_ACCEL_CTRL_START) {
        ++m->starts;
        m->polls_left = 2;
        m->regs[KECCAK_ACCEL_STATUS_OFFSET/4] = KECCAK_ACCEL_STATUS_BUSY;
    } else if (offset >= KECCAK_ACCEL_STATE_OFFSET &&
               offset < KECCAK_ACCEL_STATE_OFFSET + 200) {
        m->regs[offset/4] = value;
        ++m->state_writes;
    } else if (offset < MOCK_WORDS * 4u) {
        m->regs[offset/4] = value;
    }
}

static unsigned fallback_calls;
static void software_fallback(uint64_t state[25])
{
    unsigned i;
    ++fallback_calls;
    for (i = 0; i < 25; ++i) state[i] ^= UINT64_C(0x1122334455667788);
}

static void init_state(uint64_t state[25])
{
    unsigned i;
    for (i = 0; i < 25; ++i) state[i] = UINT64_C(0x0102030405060708) * (i + 1u);
}

int main(void)
{
    mock_device mock;
    keccak_accel_io io;
    uint64_t state[25], original[25];
    unsigned i;

    memset(&mock, 0, sizeof(mock));
    io.opaque = &mock; io.read32 = mock_read; io.write32 = mock_write;
    io.activation_cookie = 0; // Default software mode must not probe MMIO.
    init_state(state); memcpy(original, state, sizeof(state));
    assert(keccak_accel_permute(&io, state, 8) == KECCAK_ACCEL_INVALID);
    assert(mock.reads == 0 && mock.clear_count == 0 && mock.state_writes == 0);
    fallback_calls = 0;
    assert(mlkem_keccakf1600_accel_or_fallback(&io, state, 8, software_fallback) ==
           MLKEM_KECCAK_SOFTWARE_FALLBACK);
    assert(mock.reads == 0 && mock.clear_count == 0 && fallback_calls == 1);
    init_state(state); memcpy(original, state, sizeof(state));
    io.activation_cookie = KECCAK_ACCEL_EXPERIMENTAL_ENABLE;
    mock.id_value = 0xdeadbeefu;
    assert(keccak_accel_permute(&io, state, 8) == KECCAK_ACCEL_INVALID);
    assert(mock.clear_count == 0 && mock.state_writes == 0 && memcmp(state, original, sizeof(state)) == 0);
    mock.id_value = 0; mock.version_value = 0x00020000u;
    assert(keccak_accel_permute(&io, state, 8) == KECCAK_ACCEL_INVALID);
    assert(mock.clear_count == 0 && mock.state_writes == 0);
    mock.version_value = 0;
    assert(keccak_accel_permute(&io, state, 8) == KECCAK_ACCEL_OK);
    assert(mock.starts == 1 && mock.state_writes == 50 && mock.clear_count == 2);
    for (i = 0; i < 25; ++i) {
        uint64_t lo = (uint32_t)original[i] ^ (0xa5a50000u + 2u*i);
        uint64_t hi = (uint32_t)(original[i] >> 32) ^ (0xa5a50000u + 2u*i + 1u);
        assert(state[i] == (lo | (hi << 32)));
    }
    for (i = KECCAK_ACCEL_STATE_OFFSET/4; i < (KECCAK_ACCEL_STATE_OFFSET+200)/4; ++i)
        assert(mock.regs[i] == 0);
    for (i = KECCAK_ACCEL_RESULT_OFFSET/4; i < (KECCAK_ACCEL_RESULT_OFFSET+200)/4; ++i)
        assert(mock.regs[i] == 0);

    // A bounded software timeout must clear the peripheral and preserve input.
    memset(&mock, 0, sizeof(mock)); mock.never_complete = 1;
    init_state(state); memcpy(original, state, sizeof(state));
    assert(keccak_accel_permute(&io, state, 3) == KECCAK_ACCEL_TIMEOUT);
    assert(memcmp(state, original, sizeof(state)) == 0);
    assert(mock.regs[KECCAK_ACCEL_STATUS_OFFSET/4] == 0 && mock.clear_count == 2);

    // ML-KEM adapter automatically invokes its supplied software permutation on failure.
    memset(&mock, 0, sizeof(mock)); mock.inject_error = 1;
    init_state(state); memcpy(original, state, sizeof(state)); fallback_calls = 0;
    assert(mlkem_keccakf1600_accel_or_fallback(&io, state, 8, software_fallback) ==
           MLKEM_KECCAK_SOFTWARE_FALLBACK);
    assert(fallback_calls == 1 && mock.regs[KECCAK_ACCEL_STATUS_OFFSET/4] == 0);
    for (i = 0; i < 25; ++i)
        assert(state[i] == (original[i] ^ UINT64_C(0x1122334455667788)));

    init_state(state);
    assert(mlkem_keccakf1600_accel_or_fallback(&io, state, 1, 0) == MLKEM_KECCAK_NO_FALLBACK);
    puts("KECCAK_DRIVER_MOCK_PASS mmio_words=50 default_off=1 id_version_guard=1 bounded_timeout_clear=1 sw_fallback=1");
    return 0;
}
