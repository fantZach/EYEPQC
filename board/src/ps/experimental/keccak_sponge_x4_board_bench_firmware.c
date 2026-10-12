/* Same-boot software/KX41/timeout board KAT for all 60 ML-KEM-512 vectors. */
#include "xparameters.h"
#include "xil_printf.h"
#include "xtime_l.h"
#include "keccak_sponge_x4_bench_config.h"
#include "mlkem_sponge_backend_config.h"
#include "mlkem/mlkem_native.h"
#include "keccak_accel.h"
#include "keccak_sponge_x4.h"
#include "keccak_sponge_x4_bench_kat.h"

#include <stdint.h>
#include <string.h>

#define SX4_POLL_LIMIT 2000000u
#define SX4_WATCHDOG_NORMAL 200000u
#define SX4_KAT_COUNT 60u
#define SX4_MAX_INPUT (MLKEM512_SECRETKEYBYTES + MLKEM512_CIPHERTEXTBYTES)
#define SX4_MAX_OUTPUT (MLKEM512_SECRETKEYBYTES + MLKEM512_PUBLICKEYBYTES)

_Static_assert(COUNTS_PER_SECOND > 0u && COUNTS_PER_SECOND <= UINT32_MAX,
               "XTime counter rate must fit the UART ABI");
_Static_assert(sizeof kx41_bench_vectors / sizeof kx41_bench_vectors[0] == SX4_KAT_COUNT,
               "The board KAT must contain all 60 unique vectors");

static uint8_t s_input[SX4_MAX_INPUT];
static uint8_t s_output[SX4_MAX_OUTPUT];

struct path_totals {
    uint32_t absorbs;
    uint32_t hardware_absorbs;
    uint32_t hardware_squeeze_blocks;
    uint32_t software_fallbacks;
    uint32_t timeout_fallbacks;
    uint32_t error_fallbacks;
    uint32_t timeout_status_zero_vectors;
};

static const char *operation_name(uint32_t operation)
{
    switch (operation) {
    case KX41_OP_KEYGEN: return "keygen";
    case KX41_OP_ENCAPS: return "encapsulation";
    case KX41_OP_DECAPS: return "decapsulation";
    default: return "invalid";
    }
}

static void print_ticks(const char *window, XTime ticks)
{
    xil_printf("KX41_WINDOW_TICKS window=%s hi=%08x lo=%08x\r\n", window,
               (unsigned int)(uint32_t)(ticks >> 32),
               (unsigned int)(uint32_t)ticks);
}

static int execute_vector(const kx41_bench_vector *vector)
{
    int status;
    if (vector->operation == KX41_OP_KEYGEN &&
        vector->input_len == 64U &&
        vector->output_len == MLKEM512_PUBLICKEYBYTES + MLKEM512_SECRETKEYBYTES) {
        status = eye_mlkem_keypair_derand(s_output,
            s_output + MLKEM512_PUBLICKEYBYTES, s_input);
    } else if (vector->operation == KX41_OP_ENCAPS &&
        vector->input_len == MLKEM512_PUBLICKEYBYTES + MLKEM_SYMBYTES &&
        vector->output_len == MLKEM512_CIPHERTEXTBYTES + MLKEM_BYTES) {
        status = eye_mlkem_enc_derand(s_output,
            s_output + MLKEM512_CIPHERTEXTBYTES, s_input,
            s_input + MLKEM512_PUBLICKEYBYTES);
    } else if (vector->operation == KX41_OP_DECAPS &&
        vector->input_len == MLKEM512_SECRETKEYBYTES + MLKEM512_CIPHERTEXTBYTES &&
        vector->output_len == MLKEM_BYTES) {
        status = eye_mlkem_dec(s_output,
            s_input + MLKEM512_SECRETKEYBYTES, s_input);
    } else {
        return 1;
    }
    if (status != 0 || memcmp(s_output, vector->expected, vector->output_len) != 0)
        return 1;
    return 0;
}

static int run_window(const char *window, const keccak_accel_io *io,
                      int force_timeout)
{
    XTime start, stop;
    struct path_totals totals = {0};
    uint32_t identity;
    xil_printf("KX41_WINDOW_START window=%s\r\n", window);
    if (io == NULL) {
        (void)keccak_sponge_x4_configure(NULL, 0U);
    } else {
        keccak_accel_mmio *mmio = (keccak_accel_mmio *)io->opaque;
        keccak_accel_mmio_write(mmio, KECCAK_SX4_WDOG_OFFSET,
                                SX4_WATCHDOG_NORMAL);
        identity = (uint32_t)keccak_sponge_x4_configure(io, SX4_POLL_LIMIT);
        if (!identity) {
            xil_printf("HARDWARE_CONTEXT_IDENTITY_FAIL window=%s\r\n", window);
            return 0;
        }
        xil_printf("HARDWARE_CONTEXT_IDENTITY_PASS window=%s id=%08x version=%08x\r\n",
                   window,
                   (unsigned int)KECCAK_SX4_ID_VALUE,
                   (unsigned int)KECCAK_SX4_VERSION_VALUE);
    }

    XTime_GetTime(&start);
    for (unsigned i = 0; i < SX4_KAT_COUNT; ++i) {
        const kx41_bench_vector *vector = &kx41_bench_vectors[i];
        keccak_sponge_x4_stats stats;
        if (vector->input_len > sizeof s_input || vector->output_len > sizeof s_output)
            return 0;
        memset(s_input, 0, sizeof s_input);
        memset(s_output, 0, sizeof s_output);
        memcpy(s_input, vector->input, vector->input_len);
        keccak_sponge_x4_reset_stats();
        if (force_timeout) {
            keccak_accel_mmio_write((keccak_accel_mmio *)io->opaque,
                                    KECCAK_SX4_WDOG_OFFSET, 1U);
        }
        if (execute_vector(vector)) {
            xil_printf("KX41_VECTOR_FAIL window=%s operation=%s tcId=%u\r\n",
                       window, operation_name(vector->operation),
                       (unsigned int)vector->tcid);
            memset(s_input, 0, sizeof s_input);
            memset(s_output, 0, sizeof s_output);
            return 0;
        }
        stats = keccak_sponge_x4_get_stats();
        totals.absorbs += stats.absorb_calls;
        totals.hardware_absorbs += stats.hardware_absorbs;
        totals.hardware_squeeze_blocks += stats.hardware_squeeze_blocks;
        totals.software_fallbacks += stats.software_fallbacks;
        totals.timeout_fallbacks += stats.timeout_fallbacks;
        totals.error_fallbacks += stats.error_fallbacks;

        if (force_timeout) {
            uint32_t status = keccak_accel_mmio_read(
                (keccak_accel_mmio *)io->opaque, KECCAK_SX4_STATUS_OFFSET);
            if (status != 0U || stats.timeout_fallbacks == 0U ||
                stats.hardware_squeeze_blocks != 0U) {
                xil_printf("KX41_TIMEOUT_CLEAR_FAIL tcId=%u status=%08x timeout=%u squeeze=%u\r\n",
                    (unsigned int)vector->tcid, (unsigned int)status,
                    (unsigned int)stats.timeout_fallbacks,
                    (unsigned int)stats.hardware_squeeze_blocks);
                memset(s_input, 0, sizeof s_input);
                memset(s_output, 0, sizeof s_output);
                return 0;
            }
            ++totals.timeout_status_zero_vectors;
            keccak_accel_mmio_write((keccak_accel_mmio *)io->opaque,
                                    KECCAK_SX4_WDOG_OFFSET, SX4_WATCHDOG_NORMAL);
        }
        if (io == NULL && (stats.hardware_absorbs != 0U ||
                stats.hardware_squeeze_blocks != 0U || stats.timeout_fallbacks != 0U ||
                stats.software_fallbacks != 0U || stats.error_fallbacks != 0U)) {
            xil_printf("KX41_SOFTWARE_PATH_FAIL tcId=%u\r\n", (unsigned int)vector->tcid);
            return 0;
        }
        if (io != NULL && !force_timeout &&
                (stats.hardware_absorbs == 0U || stats.hardware_squeeze_blocks == 0U ||
                 stats.software_fallbacks != 0U || stats.timeout_fallbacks != 0U ||
                 stats.error_fallbacks != 0U)) {
            xil_printf("KX41_HARDWARE_PATH_FAIL tcId=%u absorb=%u squeeze=%u fallback=%u timeout=%u error=%u\r\n",
                (unsigned int)vector->tcid, (unsigned int)stats.hardware_absorbs,
                (unsigned int)stats.hardware_squeeze_blocks,
                (unsigned int)stats.software_fallbacks,
                (unsigned int)stats.timeout_fallbacks, (unsigned int)stats.error_fallbacks);
            return 0;
        }
        memset(s_input, 0, sizeof s_input);
        memset(s_output, 0, sizeof s_output);
    }
    XTime_GetTime(&stop);

    /* UART output stays outside the measured ML-KEM windows. */
    print_ticks(window, stop - start);
    for (unsigned i = 0; i < SX4_KAT_COUNT; ++i)
        xil_printf("KX41_VECTOR_PASS window=%s operation=%s tcId=%u\r\n",
                   window, operation_name(kx41_bench_vectors[i].operation),
                   (unsigned int)kx41_bench_vectors[i].tcid);
    xil_printf("KX41_WINDOW_SUMMARY window=%s vectors=%u absorbs=%u hw_absorbs=%u hw_squeeze_blocks=%u fallback=%u timeout=%u error=%u timeout_status_zero_vectors=%u\r\n",
        window, SX4_KAT_COUNT, (unsigned int)totals.absorbs,
        (unsigned int)totals.hardware_absorbs,
        (unsigned int)totals.hardware_squeeze_blocks,
        (unsigned int)totals.software_fallbacks,
        (unsigned int)totals.timeout_fallbacks,
        (unsigned int)totals.error_fallbacks,
        (unsigned int)totals.timeout_status_zero_vectors);
    return 1;
}

int main(void)
{
    keccak_accel_mmio mmio = {
        (volatile uint32_t *)(uintptr_t)KECCAK_SX4_BENCH_MMIO_BASE
    };
    const keccak_accel_io io = {
        &mmio, keccak_accel_mmio_read, keccak_accel_mmio_write,
        KECCAK_ACCEL_EXPERIMENTAL_ENABLE
    };
    uint32_t status;
    xil_printf("KX41_BENCH board=not_asserted hw_compiled=1 counter_hz=%u vectors=60 keygen=25 encapsulation=25 decapsulation=10\r\n",
               (unsigned int)COUNTS_PER_SECOND);
    xil_printf("KX41_BENCH_VALIDATION per_vector_kat=1 identity_at_window=1\r\n");

    if (!run_window("software", NULL, 0)) return 2;
    if (!run_window("hardware", &io, 0)) return 3;
    if (!run_window("timeout_fallback", &io, 1)) return 5;
    status = keccak_accel_mmio_read(&mmio, KECCAK_SX4_STATUS_OFFSET);
    xil_printf("KX41_FINAL_STATUS=%08x\r\n", (unsigned int)status);
    if (status != 0U) return 6;
    xil_printf("KX41_FINAL_STATUS_CLEAR_PASS\r\n");
    xil_printf("KX41_TIMEOUT_MEMORY_READBACK=NOT_PERFORMED\r\n");
    keccak_accel_mmio_write(&mmio, KECCAK_SX4_WDOG_OFFSET, SX4_WATCHDOG_NORMAL);
    keccak_accel_mmio_write(&mmio, KECCAK_SX4_CTRL_OFFSET, KECCAK_SX4_CTRL_CLEAR);
    memset(s_input, 0, sizeof s_input);
    memset(s_output, 0, sizeof s_output);
    xil_printf("KX41_BENCH_DONE\r\n");
    return 0;
}
