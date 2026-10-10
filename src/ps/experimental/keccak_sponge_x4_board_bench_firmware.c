/* Same-boot SW/HW ML-KEM-512 decapsulation timing for the KX41 sponge XSA. */
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

#define SX4_BENCH_REPEAT 3u
#define SX4_POLL_LIMIT 2000000u

_Static_assert(COUNTS_PER_SECOND > 0u && COUNTS_PER_SECOND <= UINT32_MAX,
               "XTime counter rate must fit the UART ABI");

static uint8_t s_sk[MLKEM512_SECRETKEYBYTES];
static uint8_t s_ct[MLKEM512_CIPHERTEXTBYTES];
static uint8_t s_expected[MLKEM_BYTES];
static uint8_t s_ss[MLKEM_BYTES];

static void print_ticks(const char *label, XTime ticks)
{
    xil_printf("%s_ticks_hi=%08x_ticks_lo=%08x\r\n", label,
               (unsigned int)(uint32_t)(ticks >> 32),
               (unsigned int)(uint32_t)ticks);
}

static int run_decaps(const char *label, const keccak_accel_io *io,
                      int require_hardware, int require_timeout,
                      int force_timeout)
{
    XTime start, stop;
    unsigned i;
    int identity = keccak_sponge_x4_configure(io, io ? SX4_POLL_LIMIT : 0u);
    keccak_sponge_x4_stats st;
    if (io != NULL) {
        if (!identity) {
            xil_printf("HARDWARE_CONTEXT_IDENTITY_FAIL\r\n");
            return 0;
        }
        xil_printf("HARDWARE_CONTEXT_IDENTITY_PASS id=%08x version=%08x\r\n",
                   (unsigned int)KECCAK_SX4_ID_VALUE,
                   (unsigned int)KECCAK_SX4_VERSION_VALUE);
        if (force_timeout)
            keccak_accel_mmio_write((keccak_accel_mmio *)io->opaque,
                                    KECCAK_SX4_WDOG_OFFSET, 1u);
    }
    keccak_sponge_x4_reset_stats();
    XTime_GetTime(&start);
    for (i = 0; i < SX4_BENCH_REPEAT; ++i) {
        if (eye_mlkem_dec(s_ss, s_ct, s_sk) != 0) {
            xil_printf("%s DECAPS_FAIL iteration=%u\r\n", label, i);
            memset(s_ss, 0, sizeof s_ss);
            return 0;
        }
        if (memcmp(s_ss, s_expected, sizeof s_expected) != 0) {
            xil_printf("%s KAT_FAIL iteration=%u tcId=%u\r\n", label, i,
                       (unsigned int)KECCAK_SX4_BENCH_KAT_TCID);
            memset(s_ss, 0, sizeof s_ss);
            return 0;
        }
    }
    XTime_GetTime(&stop);
    /* Keep UART output outside the measured Decaps window. Each marker follows
     * an already completed per-iteration shared-secret comparison above. */
    for (i = 0; i < SX4_BENCH_REPEAT; ++i)
        xil_printf("%s KAT_ITER_PASS iteration=%u tcId=%u\r\n", label, i,
                   (unsigned int)KECCAK_SX4_BENCH_KAT_TCID);
    print_ticks(label, stop - start);
    xil_printf("%s KAT_PASS iterations=%u tcId=%u\r\n", label,
               SX4_BENCH_REPEAT, (unsigned int)KECCAK_SX4_BENCH_KAT_TCID);
    st = keccak_sponge_x4_get_stats();
    xil_printf("%s absorbs=%u hw_absorbs=%u hw_squeeze_blocks=%u fallback=%u timeout=%u error=%u\r\n",
               label, (unsigned int)st.absorb_calls,
               (unsigned int)st.hardware_absorbs,
               (unsigned int)st.hardware_squeeze_blocks,
               (unsigned int)st.software_fallbacks,
               (unsigned int)st.timeout_fallbacks,
               (unsigned int)st.error_fallbacks);
    if (require_hardware && (st.hardware_absorbs == 0u ||
            st.hardware_squeeze_blocks == 0u || st.software_fallbacks != 0u ||
            st.timeout_fallbacks != 0u || st.error_fallbacks != 0u)) {
        xil_printf("%s PATH_COUNT_FAIL\r\n", label);
        return 0;
    }
    if (require_timeout && (st.timeout_fallbacks == 0u ||
            st.software_fallbacks == 0u || st.hardware_squeeze_blocks != 0u)) {
        xil_printf("%s TIMEOUT_FALLBACK_COUNT_FAIL\r\n", label);
        return 0;
    }
    if (!require_hardware && !require_timeout &&
        (st.hardware_absorbs != 0u || st.hardware_squeeze_blocks != 0u ||
         st.timeout_fallbacks != 0u || st.error_fallbacks != 0u)) {
        xil_printf("%s SOFTWARE_PATH_COUNT_FAIL\r\n", label);
        return 0;
    }
    memset(s_ss, 0, sizeof s_ss);
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
    memcpy(s_sk, keccak_sponge_x4_bench_sk, sizeof s_sk);
    memcpy(s_ct, keccak_sponge_x4_bench_ct, sizeof s_ct);
    memcpy(s_expected, keccak_sponge_x4_bench_ss, sizeof s_expected);
    xil_printf("KECCAK_SX4_BENCH board=not_asserted hw_compiled=1 counter_hz=%u\r\n",
               (unsigned int)COUNTS_PER_SECOND);
    xil_printf("KECCAK_SX4_BENCH_VALIDATION per_iteration_kat=1 identity_at_configure=1\r\n");

    /* Software, real MMIO hardware, and forced watchdog fallback share one
     * boot and the exact same tcId 76 material and per-iteration KAT work. */
    if (!run_decaps("software_mlkem512_decaps_3", NULL, 0, 0, 0)) return 2;
    if (!run_decaps("hardware_mlkem512_decaps_3", &io, 1, 0, 0)) return 3;
    if (!run_decaps("timeout_fallback_mlkem512_decaps_3", &io, 0, 1, 1)) return 5;
    status = keccak_accel_mmio_read(&mmio, KECCAK_SX4_STATUS_OFFSET);
    xil_printf("timeout_clear_status=%08x\r\n", (unsigned int)status);
    if (status != 0u) return 6;
    xil_printf("TIMEOUT_STATUS_CLEAR_PASS\r\n");
    xil_printf("TIMEOUT_STATUS_ONLY_CHECK_NO_STATE_RESULT_READBACK\r\n");
    keccak_accel_mmio_write(&mmio, KECCAK_SX4_WDOG_OFFSET, 200000u);
    keccak_accel_mmio_write(&mmio, KECCAK_SX4_CTRL_OFFSET, KECCAK_SX4_CTRL_CLEAR);
    memset(s_sk, 0, sizeof s_sk); memset(s_ct, 0, sizeof s_ct);
    memset(s_expected, 0, sizeof s_expected); memset(s_ss, 0, sizeof s_ss);
    xil_printf("KECCAK_SX4_BENCH_DONE\r\n");
    return 0;
}
