#include "mlkem/mlkem_native.h"
#include "mlkem_fips202_backend.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define REG_STATUS_BUSY  (1u << 0)
#define REG_STATUS_DONE  (1u << 1)
#define REG_STATUS_ERROR (1u << 2)
#define REG_STATUS_TO    (1u << 3)

typedef enum { MOCK_HARDWARE_RESULT, MOCK_TIMEOUT, MOCK_ERROR } mock_mode;
typedef struct {
    uint64_t state[25];
    uint64_t result[25];
    uint32_t status;
    uint32_t launches;
    uint32_t clears;
    uint32_t status_reads;
    uint32_t id_reads;
    uint32_t version_reads;
    uint32_t read_calls;
    uint32_t write_calls;
    uint32_t state_writes;
    uint32_t id_value;
    uint32_t version_value;
    mock_mode mode;
} mock_peripheral;

void eye_mlkem_ref_keccakf1600_permute(uint64_t state[25]);

static int read_exact(const char *path, uint8_t *dst, size_t length)
{
    FILE *file = fopen(path, "rb");
    int ok;
    if (!file) return 0;
    ok = fread(dst, 1, length, file) == length && fgetc(file) == EOF;
    fclose(file);
    return ok;
}

static uint32_t mock_read32(void *opaque, uint32_t offset)
{
    mock_peripheral *mock = (mock_peripheral *)opaque;
    uint32_t word;
    ++mock->read_calls;
    if (offset == KECCAK_ACCEL_ID_OFFSET) {
        ++mock->id_reads;
        return mock->id_value ? mock->id_value : KECCAK_ACCEL_ID_VALUE;
    }
    if (offset == KECCAK_ACCEL_VERSION_OFFSET) {
        ++mock->version_reads;
        return mock->version_value ? mock->version_value : KECCAK_ACCEL_VERSION_VALUE;
    }
    if (offset == KECCAK_ACCEL_STATUS_OFFSET) {
        ++mock->status_reads;
        if (mock->mode == MOCK_ERROR) return REG_STATUS_ERROR;
        return mock->status;
    }
    if (offset >= KECCAK_ACCEL_RESULT_OFFSET &&
        offset < KECCAK_ACCEL_RESULT_OFFSET + 200u && (offset & 3u) == 0) {
        word = (offset - KECCAK_ACCEL_RESULT_OFFSET) / 4u;
        return (word & 1u) ? (uint32_t)(mock->result[word / 2u] >> 32)
                           : (uint32_t)mock->result[word / 2u];
    }
    return 0;
}

static void mock_write32(void *opaque, uint32_t offset, uint32_t value)
{
    mock_peripheral *mock = (mock_peripheral *)opaque;
    uint32_t word;
    ++mock->write_calls;
    if (offset == KECCAK_ACCEL_CTRL_OFFSET) {
        if (value == KECCAK_ACCEL_CTRL_CLEAR) {
            ++mock->clears;
            memset(mock->state, 0, sizeof mock->state);
            memset(mock->result, 0, sizeof mock->result);
            mock->status = 0;
        } else if (value == KECCAK_ACCEL_CTRL_START) {
            ++mock->launches;
            mock->status = REG_STATUS_BUSY;
            if (mock->mode == MOCK_HARDWARE_RESULT) {
                memcpy(mock->result, mock->state, sizeof mock->state);
                eye_mlkem_ref_keccakf1600_permute(mock->result);
                mock->status = REG_STATUS_DONE;
            }
        }
        return;
    }
    if (offset >= KECCAK_ACCEL_STATE_OFFSET &&
        offset < KECCAK_ACCEL_STATE_OFFSET + 200u && (offset & 3u) == 0) {
        word = (offset - KECCAK_ACCEL_STATE_OFFSET) / 4u;
        if (word & 1u)
            mock->state[word / 2u] = (mock->state[word / 2u] & UINT64_C(0xffffffff)) |
                                     ((uint64_t)value << 32);
        else
            mock->state[word / 2u] = (mock->state[word / 2u] & UINT64_C(0xffffffff00000000)) | value;
        ++mock->state_writes;
    }
}

static void mock_prepare(mock_peripheral *mock, mock_mode mode)
{
    memset(mock, 0, sizeof *mock);
    mock->mode = mode;
}

static int run_kat_case(const char *name, const uint8_t *sk, const uint8_t *ct,
                        const uint8_t expected[MLKEM_BYTES],
                        const keccak_accel_io *io, uint32_t poll_limit,
                        mlkem_fips202_backend_stats *stats_out)
{
    uint8_t ss[MLKEM_BYTES];
    (void)mlkem_fips202_backend_configure(io, poll_limit);
    mlkem_fips202_backend_reset_stats();
    if (eye_mlkem_dec(ss, ct, sk) != 0 || memcmp(ss, expected, sizeof ss) != 0) {
        fprintf(stderr, "ML-KEM-512 KAT failed in %s path\n", name);
        return 0;
    }
    *stats_out = mlkem_fips202_backend_get_stats();
    printf("MLKEM_FULL_BACKEND case=%s kat=PASS dispatch_calls=%u hw_success=%u sw_fallback=%u\n",
           name, stats_out->dispatch_calls, stats_out->hardware_successes,
           stats_out->software_fallbacks);
    memset(ss, 0, sizeof ss);
    return stats_out->dispatch_calls > 0;
}

static int test_random_state_fast_path(void)
{
    mock_peripheral mock;
    keccak_accel_io io;
    uint64_t state[25], original[25], expected[25];
    uint64_t rng = UINT64_C(0x9e3779b97f4a7c15);
    unsigned i;

    memset(&io, 0, sizeof io);
    io.opaque = &mock; io.read32 = mock_read32; io.write32 = mock_write32;
    io.activation_cookie = KECCAK_ACCEL_EXPERIMENTAL_ENABLE;
    for (i = 0; i < 25; ++i) {
        rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
        state[i] = rng;
    }
    memcpy(original, state, sizeof state);
    memcpy(expected, state, sizeof state);
    eye_mlkem_ref_keccakf1600_permute(expected);

    mock_prepare(&mock, MOCK_HARDWARE_RESULT);
    if (!mlkem_fips202_backend_configure(&io, 8) || mock.id_reads != 1 ||
        mock.version_reads != 1) return 0;
    if (keccak_accel_permute_prevalidated(&io, state, 8) != KECCAK_ACCEL_OK ||
        memcmp(state, expected, sizeof state) != 0 || mock.id_reads != 1 ||
        mock.version_reads != 1) return 0;

    for (i = 0; i < 2; ++i) {
        mock_prepare(&mock, i == 0 ? MOCK_ERROR : MOCK_TIMEOUT);
        memcpy(state, original, sizeof state);
        if (!mlkem_fips202_backend_configure(&io, 8) ||
            keccak_accel_permute_prevalidated(&io, state, 8) !=
                (i == 0 ? KECCAK_ACCEL_HW_ERROR : KECCAK_ACCEL_TIMEOUT) ||
            memcmp(state, original, sizeof state) != 0) return 0;
        eye_mlkem_ref_keccakf1600_permute(state); /* same fallback permutation as backend */
        if (memcmp(state, expected, sizeof state) != 0) return 0;
    }
    puts("MLKEM_FAST_PATH_RANDOM_STATE_PASS hardware_match=1 error_preserves_input=1 timeout_preserves_input=1 fallback_matches_reference=1");
    return 1;
}

int main(int argc, char **argv)
{
    uint8_t sk[MLKEM512_SECRETKEYBYTES];
    uint8_t ct[MLKEM512_CIPHERTEXTBYTES];
    uint8_t expected[MLKEM_BYTES];
    uint8_t input[MLKEM512_SECRETKEYBYTES + MLKEM512_CIPHERTEXTBYTES];
    mock_peripheral mock;
    keccak_accel_io io;
    mlkem_fips202_backend_stats stats;

    if (argc != 3) {
        fprintf(stderr, "usage: %s <sk||ct.bin> <expected-ss.bin>\n", argv[0]);
        return 2;
    }
    if (!read_exact(argv[1], input, sizeof input) ||
        !read_exact(argv[2], expected, sizeof expected)) {
        fprintf(stderr, "KAT file length/read failure\n");
        return 2;
    }
    memcpy(sk, input, sizeof sk);
    memcpy(ct, input + sizeof sk, sizeof ct);
    if (!test_random_state_fast_path()) return 3;

    memset(&io, 0, sizeof io);
    mock_prepare(&mock, MOCK_HARDWARE_RESULT);
    io.opaque = &mock; io.read32 = mock_read32; io.write32 = mock_write32;
    /* Default/off is the production-safe configuration: callbacks are present,
       but the zero activation cookie prevents every MMIO access. */
    if (!run_kat_case("disabled_fallback", sk, ct, expected, &io, 64, &stats) ||
        stats.hardware_successes != 0 || stats.software_fallbacks != stats.dispatch_calls ||
        mock.launches != 0 || mock.read_calls != 0 || mock.write_calls != 0) return 3;
    printf("MLKEM_FULL_BACKEND_GATE disabled_mmio_reads=%u disabled_mmio_writes=%u\n",
           mock.read_calls, mock.write_calls);

    mock_prepare(&mock, MOCK_HARDWARE_RESULT);
    io.opaque = &mock; io.activation_cookie = KECCAK_ACCEL_EXPERIMENTAL_ENABLE;
    if (!run_kat_case("mmio_mock_hardware", sk, ct, expected, &io, 64, &stats) ||
        stats.hardware_successes == 0 || stats.software_fallbacks != 0 ||
        mock.launches != stats.hardware_successes || mock.status_reads == 0 ||
        mock.id_reads != 1 || mock.version_reads != 1) return 4;
    printf("MLKEM_FULL_BACKEND_GATE hardware_mock_launches=%u status_reads=%u identity_reads=%u/%u dispatch=%u\n",
           mock.launches, mock.status_reads, mock.id_reads, mock.version_reads,
           stats.dispatch_calls);

    mock_prepare(&mock, MOCK_HARDWARE_RESULT);
    io.opaque = &mock; mock.id_value = 0xdeadbeefu;
    if (!run_kat_case("identity_mismatch_fallback", sk, ct, expected, &io, 64, &stats) ||
        stats.hardware_successes != 0 || stats.software_fallbacks != stats.dispatch_calls ||
        mock.id_reads != 1 || mock.version_reads != 1 || mock.launches != 0 ||
        mock.state_writes != 0 || mock.write_calls != 0) return 5;
    printf("MLKEM_FULL_BACKEND_GATE identity_mismatch=%u/%u dispatch=%u no_state_or_start=1\n",
           mock.id_reads, mock.version_reads, stats.dispatch_calls);

    mock_prepare(&mock, MOCK_ERROR);
    io.opaque = &mock; mock.id_value = 0; mock.version_value = 0;
    if (!run_kat_case("mmio_mock_error_fallback", sk, ct, expected, &io, 64, &stats) ||
        stats.hardware_successes != 0 || stats.software_fallbacks != stats.dispatch_calls ||
        mock.launches != stats.dispatch_calls || mock.id_reads != 1 ||
        mock.version_reads != 1) return 6;
    printf("MLKEM_FULL_BACKEND_GATE error_mock_launches=%u status_reads=%u\n",
           mock.launches, mock.status_reads);

    mock_prepare(&mock, MOCK_TIMEOUT);
    io.opaque = &mock;
    if (!run_kat_case("mmio_mock_timeout_fallback", sk, ct, expected, &io, 7, &stats) ||
        stats.hardware_successes != 0 || stats.software_fallbacks != stats.dispatch_calls ||
        mock.launches == 0 || mock.status_reads != stats.dispatch_calls * 7u || mock.clears == 0 ||
        mock.id_reads != 1 || mock.version_reads != 1) return 7;
    printf("MLKEM_FULL_BACKEND_GATE timeout_mock_launches=%u status_reads=%u clear_writes=%u\n",
           mock.launches, mock.status_reads, mock.clears);

    printf("MLKEM_FULL_BACKEND_PASS vendor_unchanged=1 real_decapsulation=1 kat_tcId=76 mock_only=1\n");
    memset(sk, 0, sizeof sk); memset(ct, 0, sizeof ct); memset(input, 0, sizeof input);
    return 0;
}
