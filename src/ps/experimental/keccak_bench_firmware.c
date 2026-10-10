/* Independent PS/PL Keccak benchmark. Build with KECCAK_BENCH_ENABLE_HW=0 by
 * default; enabling HW is valid only with the matching experimental XSA. */
#include "xparameters.h"
#include "xil_printf.h"
#include "xtime_l.h"
#include "keccak_bench_config.h"
#include "mlkem_full_backend_config.h"
#include "mlkem/mlkem_native.h"
#include "keccak_accel.h"
#include "mlkem_fips202_backend.h"
#include "keccak_bench_kat.h"

#include <stdint.h>
#include <string.h>

#ifndef KECCAK_BENCH_ENABLE_HW
#define KECCAK_BENCH_ENABLE_HW 0
#endif
#ifndef KECCAK_BENCH_MMIO_BASE
#define KECCAK_BENCH_MMIO_BASE 0x43C10000u
#endif
#define KAT_REPEAT 3u
#define POLL_LIMIT 2000000u
#define STATE_WORDS 50u

_Static_assert(COUNTS_PER_SECOND > 0u && COUNTS_PER_SECOND <= UINT32_MAX,
               "UART counter_hz field must fit the firmware's 32-bit xil_printf ABI");

void eye_mlkem_ref_keccakf1600_permute(uint64_t state[25]);
static uint8_t s_secret_key[MLKEM512_SECRETKEYBYTES];
static uint8_t s_ciphertext[MLKEM512_CIPHERTEXTBYTES];
static uint8_t s_expected[MLKEM_BYTES];
static uint8_t s_shared_secret[MLKEM_BYTES];
#if KECCAK_BENCH_ENABLE_HW
static volatile uint32_t s_bus_sink;
#endif

static void output_hex(const char *label, XTime ticks)
{
    uint32_t hi = (uint32_t)(ticks >> 32);
    uint32_t lo = (uint32_t)(ticks & UINT64_C(0xffffffff));
    xil_printf("%s_ticks_hi=%08x_ticks_lo=%08x\r\n", label,
               (unsigned int)hi, (unsigned int)lo);
}

#if KECCAK_BENCH_ENABLE_HW
static uint32_t hw_read(void *opaque, uint32_t offset)
{
    keccak_accel_mmio *m = (keccak_accel_mmio *)opaque;
    return m->base[offset >> 2];
}

static void hw_write(void *opaque, uint32_t offset, uint32_t value)
{
    keccak_accel_mmio *m = (keccak_accel_mmio *)opaque;
    m->base[offset >> 2] = value;
}

static int wait_for_done(keccak_accel_mmio *mmio, uint32_t poll_limit)
{
    uint32_t poll, status;
    for (poll = 0; poll < poll_limit; ++poll) {
        status = hw_read(mmio, KECCAK_ACCEL_STATUS_OFFSET);
        if (status & (KECCAK_ACCEL_STATUS_ERROR | KECCAK_ACCEL_STATUS_TIMEOUT))
            return 0;
        if ((status & KECCAK_ACCEL_STATUS_DONE) && !(status & KECCAK_ACCEL_STATUS_BUSY))
            return 1;
    }
    return 0;
}
#endif

static int run_decaps(const char *label, const keccak_accel_io *io,
                      uint32_t poll_limit, uint32_t repeat,
                      uint8_t expect_hardware, uint8_t expect_fallback)
{
    XTime start, stop;
    uint32_t i;
    mlkem_fips202_backend_configure(io, poll_limit);
    mlkem_fips202_backend_reset_stats();
    XTime_GetTime(&start);
    for (i = 0; i < repeat; ++i) {
        if (eye_mlkem_dec(s_shared_secret, s_ciphertext, s_secret_key) != 0) {
            xil_printf("%s DECAPS_FAIL iteration=%u\r\n", label, (unsigned int)i);
            memset(s_shared_secret, 0, sizeof s_shared_secret);
            return 0;
        }
    }
    XTime_GetTime(&stop);
    output_hex(label, stop - start);
    if (memcmp(s_shared_secret, s_expected, sizeof s_expected) != 0) {
        xil_printf("%s KAT_FAIL\r\n", label);
        memset(s_shared_secret, 0, sizeof s_shared_secret);
        return 0;
    }
    {
        mlkem_fips202_backend_stats st = mlkem_fips202_backend_get_stats();
        xil_printf("%s dispatch=%u hw=%u fallback=%u\r\n", label,
                   (unsigned int)st.dispatch_calls,
                   (unsigned int)st.hardware_successes,
                   (unsigned int)st.software_fallbacks);
        if ((expect_hardware && (st.hardware_successes == 0 || st.software_fallbacks != 0)) ||
            (expect_fallback && (st.hardware_successes != 0 || st.software_fallbacks != st.dispatch_calls))) {
            xil_printf("%s PATH_COUNT_FAIL\r\n", label);
            memset(s_shared_secret, 0, sizeof s_shared_secret);
            return 0;
        }
    }
    memset(s_shared_secret, 0, sizeof s_shared_secret);
    return 1;
}

int main(void)
{
    uint64_t software_state[25] = {0};
    XTime start, stop;
    unsigned i;
    const keccak_accel_io disabled = {0};

    memcpy(s_secret_key, keccak_bench_sk, sizeof s_secret_key);
    memcpy(s_ciphertext, keccak_bench_ct, sizeof s_ciphertext);
    memcpy(s_expected, keccak_bench_ss, sizeof s_expected);
    xil_printf("KECCAK_BENCH board=not_asserted hw_compiled=%u counter_hz=%u\r\n",
               (unsigned)KECCAK_BENCH_ENABLE_HW,
               (unsigned int)COUNTS_PER_SECOND);

    /* Same-board software Keccak baseline. These counts are PS measurements
     * only when this image is later run on the target board. */
    XTime_GetTime(&start);
    for (i = 0; i < 100; ++i) {
        software_state[0] = (uint64_t)i;
        eye_mlkem_ref_keccakf1600_permute(software_state);
    }
    XTime_GetTime(&stop);
    output_hex("software_keccak_100_permutations", stop - start);
    memset(software_state, 0, sizeof software_state);
    if (!run_decaps("software_mlkem512_decaps_3", &disabled, 0, KAT_REPEAT, 0, 1)) return 2;

#if KECCAK_BENCH_ENABLE_HW
    {
        keccak_accel_mmio mmio = {(volatile uint32_t *)(uintptr_t)KECCAK_BENCH_MMIO_BASE};
        keccak_accel_io io = {&mmio, hw_read, hw_write, KECCAK_ACCEL_EXPERIMENTAL_ENABLE};
        uint32_t id, version;
        uint32_t in_words[STATE_WORDS] = {0};
        XTime write_start, write_stop, read_start, read_stop;
        XTime write_ticks, read_ticks;
        /* Only this explicitly enabled image probes the address. It must be
         * paired with the standalone XSA whose manifest records this map. */
        id = hw_read(&mmio, KECCAK_ACCEL_ID_OFFSET);
        version = hw_read(&mmio, KECCAK_ACCEL_VERSION_OFFSET);
        xil_printf("hardware_gate id=%08x version=%08x expected=%08x/%08x\r\n",
                   (unsigned int)id, (unsigned int)version,
                   (unsigned int)KECCAK_ACCEL_ID_VALUE,
                   (unsigned int)KECCAK_ACCEL_VERSION_VALUE);
        if (id != KECCAK_ACCEL_ID_VALUE || version != KECCAK_ACCEL_VERSION_VALUE) {
            xil_printf("HARDWARE_DISABLED identity_mismatch\r\n");
            return 3;
        }
        hw_write(&mmio, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_CLEAR);
        XTime_GetTime(&write_start);
        for (i = 0; i < STATE_WORDS; ++i)
            hw_write(&mmio, KECCAK_ACCEL_STATE_OFFSET + 4u * i, in_words[i]);
        __asm__ volatile("dmb sy" ::: "memory");
        XTime_GetTime(&write_stop);
        write_ticks = write_stop - write_start;

        /* Start and bounded completion polling are outside the transfer timers.
         * RESULT reads are legal only after DONE and !BUSY are observed. */
        hw_write(&mmio, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_START);
        if (!wait_for_done(&mmio, POLL_LIMIT)) {
            hw_write(&mmio, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_CLEAR);
            xil_printf("MMIO_TRANSFER_PERMUTE_FAIL status_poll_bounded\r\n");
            return 8;
        }
        __asm__ volatile("dmb sy" ::: "memory");
        xil_printf("MMIO_TRANSFER_RESULT_READ_GATED_DONE_PASS\r\n");
        XTime_GetTime(&read_start);
        for (i = 0; i < STATE_WORDS; ++i)
            s_bus_sink ^= hw_read(&mmio, KECCAK_ACCEL_RESULT_OFFSET + 4u * i);
        XTime_GetTime(&read_stop);
        read_ticks = read_stop - read_start;
        output_hex("mmio_transfer_50_state_write", write_ticks);
        output_hex("mmio_transfer_50_result_read_after_done", read_ticks);
        output_hex("mmio_transfer_50_write_50_read_excluding_permutation",
                   write_ticks + read_ticks);
        hw_write(&mmio, KECCAK_ACCEL_CTRL_OFFSET, KECCAK_ACCEL_CTRL_CLEAR);

        {
            uint64_t state[25] = {0};
            state[0] = UINT64_C(0x0706050403020100);
            XTime_GetTime(&start);
            if (keccak_accel_permute(&io, state, POLL_LIMIT) != KECCAK_ACCEL_OK) {
                XTime_GetTime(&stop);
                output_hex("hardware_single_permutation_failed_elapsed", stop - start);
                xil_printf("HARDWARE_PERMUTE_FAIL\r\n");
                memset(state, 0, sizeof state);
                return 4;
            }
            XTime_GetTime(&stop);
            output_hex("hardware_single_permutation_including_mmio", stop - start);
            memset(state, 0, sizeof state);
        }
        if (!run_decaps("hardware_mlkem512_decaps_3", &io, POLL_LIMIT,
                        KAT_REPEAT, 1, 0)) return 5;
        hw_write(&mmio, KECCAK_ACCEL_WATCHDOG_OFFSET, 1u);
        if (!run_decaps("timeout_fallback_mlkem512_decaps_3", &io, POLL_LIMIT,
                        KAT_REPEAT, 0, 1)) return 6;
        {
            uint32_t status = hw_read(&mmio, KECCAK_ACCEL_STATUS_OFFSET);
            xil_printf("timeout_clear_status=%08x\r\n", (unsigned int)status);
            if (status != 0) return 7;
            xil_printf("TIMEOUT_STATUS_CLEAR_PASS\r\n");
            xil_printf("TIMEOUT_STATUS_ONLY_CHECK_NO_STATE_RESULT_READBACK\r\n");
        }
        hw_write(&mmio, KECCAK_ACCEL_WATCHDOG_OFFSET, 1024u);
    }
#else
    xil_printf("HARDWARE_NOT_COMPILED no_mmio_probe\r\n");
#endif

    memset(s_secret_key, 0, sizeof s_secret_key);
    memset(s_ciphertext, 0, sizeof s_ciphertext);
    memset(s_expected, 0, sizeof s_expected);
    memset(s_shared_secret, 0, sizeof s_shared_secret);
    xil_printf("KECCAK_BENCH_DONE\r\n");
    return 0;
}
