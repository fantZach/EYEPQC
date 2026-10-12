/* M09: volatile JTAG-provisioned static key, offline ML-KEM-512 Decaps. */
#include "xparameters.h"
#include "xil_cache.h"
#include "xil_printf.h"
#include "xiltimer.h"
#include "sleep.h"
#define MLK_CONFIG_PARAMETER_SET 512
#define MLK_CONFIG_NAMESPACE_PREFIX eye_mlkem
#define MLK_CONFIG_NO_RANDOMIZED_API
#define MLK_CONFIG_NO_SUPERCOP
#define MLK_CONFIG_NO_KEYPAIR_API
#define MLK_CONFIG_NO_ENCAPS_API
#include "mlkem/mlkem_native.h"
#include <stdint.h>
#include <stddef.h>

#define MAGIC 0x39304d45U /* EM09 */
#define SK_BYTES 1632U
#define CT_BYTES 768U
#define SS_BYTES 32U

struct m09_job {
    uint32_t magic, state, command, status, iterations, reserved, stack_bytes, heap_bytes;
    uint64_t ticks, cycles, elapsed_us;
    uint8_t shared[SS_BYTES], padding[40];
};
volatile struct m09_job m09_job __attribute__((aligned(64)));
volatile uint8_t m09_sk[SK_BYTES] __attribute__((aligned(64)));
volatile uint8_t m09_ct[CT_BYTES] __attribute__((aligned(64)));
static uint8_t private_key[SK_BYTES];
static int loaded;
extern char _stack_end;

_Static_assert(sizeof(struct m09_job) == 128, "mailbox ABI");
_Static_assert(offsetof(struct m09_job, shared) == 56, "shared offset");

static void wipe(volatile void *memory, unsigned n)
{
    volatile uint8_t *p = memory;
    while (n--) *p++ = 0;
}

static unsigned run_job(void)
{
    XTime start, end;
    uintptr_t sp;
    volatile uint8_t *first = (volatile uint8_t *)&_stack_end;
    volatile uint8_t *limit;
    uint8_t shared[SS_BYTES] = {0};
    unsigned count = m09_job.iterations;
    unsigned status = 0;
    m09_job.stack_bytes = m09_job.heap_bytes = 0;
    m09_job.ticks = m09_job.cycles = m09_job.elapsed_us = 0;
    wipe(m09_job.shared, SS_BYTES);
    if (m09_job.command == 3) {
        wipe(private_key, SK_BYTES);
        wipe(m09_sk, SK_BYTES);
        loaded = 0;
        return 0;
    }
    if (m09_job.command == 1) {
        wipe(private_key, SK_BYTES);
        loaded = 0;
        for (unsigned i = 0; i < SK_BYTES; ++i) private_key[i] = m09_sk[i];
        wipe(m09_sk, SK_BYTES);
        if (eye_mlkem_check_sk(private_key)) {
            wipe(private_key, SK_BYTES);
            return 2;
        }
        loaded = 1;
        return 0;
    }
    if (m09_job.command != 2 || !loaded || count == 0 || count > 1000) return 1;
    __asm__ volatile("mov %0, sp" : "=r"(sp));
    if (sp <= (uintptr_t)first + 512U) return 3;
    limit = (volatile uint8_t *)(sp - 256U);
    for (volatile uint8_t *p = first; p < limit; ++p) *p = 0xa5;
    XTime_GetTime(&start);
    for (unsigned i = 0; i < count; ++i) {
        if (eye_mlkem_dec(shared, (const uint8_t *)m09_ct, private_key)) {
            status = 4;
            break;
        }
    }
    XTime_GetTime(&end);
    while (first < limit && *first == 0xa5) ++first;
    m09_job.stack_bytes = (uint32_t)(sp - (uintptr_t)first);
    m09_job.ticks = end - start;
    m09_job.cycles = m09_job.ticks * XPAR_CPU_CORE_CLOCK_FREQ_HZ / (COUNTS_PER_SECOND);
    m09_job.elapsed_us = m09_job.ticks * 1000000ULL / (COUNTS_PER_SECOND);
    if (!status) for (unsigned i = 0; i < SS_BYTES; ++i) m09_job.shared[i] = shared[i];
    wipe(shared, SS_BYTES);
    return status;
}

int main(void)
{
    Xil_DCacheDisable();
    usleep(1); /* Start xiltimer before the benchmark. */
    m09_job.magic = MAGIC;
    xil_printf("M09 READY mailbox=%08x sk=%08x ct=%08x\r\n",
               (unsigned)(UINTPTR)&m09_job, (unsigned)(UINTPTR)m09_sk,
               (unsigned)(UINTPTR)m09_ct);
    for (;;) if (m09_job.state == 1) {
        m09_job.state = 4;
        m09_job.status = run_job();
        __asm__ volatile("dsb sy" ::: "memory");
        m09_job.state = m09_job.status ? 3 : 2;
    }
}
