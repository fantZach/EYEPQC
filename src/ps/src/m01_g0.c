/* Standalone non-network G0 acceptance application. */
#include "xparameters.h"
#include "xil_assert.h"
#include "xil_cache.h"
#include "xil_exception.h"
#include "xil_printf.h"
#include "xil_testmem.h"
#include "xtime_l.h"
#include "xscugic.h"
#include "xscutimer.h"
#include "xuartps.h"
#include "xil_io.h"
#include "g0_build_id.h"

#define G0_BOOT_MODE_REG 0xF800025CU /* Zynq-7000 UG585 SLCR BOOT_MODE. */
#define G0_BOOT_MODE_MASK 0x1FU
#define G0_SD_BOOT_MODE 0x05U
#define G0_SCRATCH_WORDS 16384U
#define G0_TICKS_PER_SECOND 20U

enum g0_status { G0_OK, G0_UART, G0_DDR, G0_TIMER, G0_ASSERT, G0_EXCEPTION };

static struct {
    u32 ddr_passes;
    u32 ddr_errors;
    u32 assertions;
    u32 exceptions;
    u32 timer_errors;
} stats;
static volatile u32 ticks;
static XScuTimer timer;
static XScuGic interrupt_controller;
static u32 scratch[G0_SCRATCH_WORDS] __attribute__((aligned(64)));

static void fail(enum g0_status code, const char *where)
{
    Xil_ExceptionDisable();
    xil_printf("G0 FAIL code=%u where=%s uptime_ticks=%u\r\n", code, where, ticks);
    for (;;) { }
}

static void assertion(const char8 *file, s32 line)
{
    stats.assertions++;
    xil_printf("G0 ASSERT file=%s line=%d\r\n", file, line);
    fail(G0_ASSERT, "assert");
}

static void exception(void *id)
{
    stats.exceptions++;
    xil_printf("G0 EXCEPTION id=%u\r\n", (u32)(UINTPTR)id);
    fail(G0_EXCEPTION, "exception");
}

static int ddr_test(int cached)
{
    u32 i;
    volatile u32 *memory = scratch;

    if (!cached && Xil_TestMem32(scratch, G0_SCRATCH_WORDS, 0xA5A55A5AU,
                                 XIL_TESTMEM_ALLMEMTESTS) != XST_SUCCESS) {
        return G0_DDR;
    }
    for (i = 0; i < G0_SCRATCH_WORDS; ++i) memory[i] = i ^ 0x5AA5A55AU;
    if (cached) {
        Xil_DCacheFlushRange((INTPTR)scratch, sizeof scratch);
        Xil_DCacheInvalidateRange((INTPTR)scratch, sizeof scratch);
    }
    for (i = 0; i < G0_SCRATCH_WORDS; ++i) {
        if (memory[i] != (i ^ 0x5AA5A55AU)) return G0_DDR;
    }
    stats.ddr_passes++;
    return G0_OK;
}

static void timer_irq(void *instance)
{
    XScuTimer *instance_timer = instance;
    if (XScuTimer_IsExpired(instance_timer)) {
        XScuTimer_ClearInterruptStatus(instance_timer);
        ticks++;
    }
}

static int timer_start(void)
{
    XScuTimer_Config *cfg = XScuTimer_LookupConfig(XPAR_XSCUTIMER_0_DEVICE_ID);
    XScuGic_Config *gic_cfg = XScuGic_LookupConfig(XPAR_SCUGIC_0_DEVICE_ID);
    if (!cfg || XScuTimer_CfgInitialize(&timer, cfg, cfg->BaseAddr) != XST_SUCCESS ||
        XScuTimer_SelfTest(&timer) != XST_SUCCESS) return G0_TIMER;
    if (!gic_cfg || XScuGic_CfgInitialize(&interrupt_controller, gic_cfg,
                                           gic_cfg->CpuBaseAddress) != XST_SUCCESS)
        return G0_TIMER;
    XScuTimer_SetPrescaler(&timer, 0);
    /* Zynq-7000 Cortex-A9 private timer is clocked at CPU/2. */
    XScuTimer_LoadTimer(&timer, XPAR_CPU_CORTEXA9_CORE_CLOCK_FREQ_HZ / 40U);
    XScuTimer_EnableAutoReload(&timer);
    Xil_ExceptionInit();
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_UNDEFINED_INT, exception, (void *)1);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_SWI_INT, exception, (void *)2);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_PREFETCH_ABORT_INT, exception, (void *)3);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_DATA_ABORT_INT, exception, (void *)4);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_FIQ_INT, exception, (void *)6);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_INT,
                                 (Xil_ExceptionHandler)XScuGic_InterruptHandler,
                                 &interrupt_controller);
    if (XScuGic_Connect(&interrupt_controller, XPAR_SCUTIMER_INTR,
                        (Xil_InterruptHandler)timer_irq, &timer) != XST_SUCCESS)
        return G0_TIMER;
    XScuGic_Enable(&interrupt_controller, XPAR_SCUTIMER_INTR);
    XScuTimer_EnableInterrupt(&timer);
    XScuTimer_Start(&timer);
    Xil_ExceptionEnable();
    return G0_OK;
}

static u32 read_boot_mode(void)
{
    /* UG585: sampled straps are read-only at SLCR 0xF800025C; SD is 0x05. */
    return Xil_In32(G0_BOOT_MODE_REG) & G0_BOOT_MODE_MASK;
}

int main(void)
{
    XUartPs uart;
    XUartPs_Config *uart_cfg = XUartPs_LookupConfig(XPAR_XUARTPS_0_DEVICE_ID);
    XTime now, previous_time;
    u32 seconds = 0, previous_ticks = 0;
    u32 boot_mode = read_boot_mode();
    int code;

    Xil_AssertSetCallback(assertion);
    if (!uart_cfg || XUartPs_CfgInitialize(&uart, uart_cfg, uart_cfg->BaseAddress) != XST_SUCCESS ||
        XUartPs_SetBaudRate(&uart, 115200) != XST_SUCCESS) fail(G0_UART, "UART0");
    xil_printf("\r\nG0 BOOT build=%s boot_mode=0x%02x cpu_hz=%u FCLK0=100000000 "
               "UART=115200 LED=PL_H15 heartbeat_hz=1\r\n",
               G0_BUILD_ID, boot_mode, XPAR_CPU_CORTEXA9_CORE_CLOCK_FREQ_HZ);
    Xil_DCacheDisable();
    code = ddr_test(0);
    Xil_DCacheEnable();
    if (code == G0_OK) code = ddr_test(1);
    if (code != G0_OK) {
        stats.ddr_errors++;
        xil_printf("G0 DDR FAIL uncached_or_cached\r\n");
        fail(G0_DDR, "DDR boot");
    }
    xil_printf("G0 DDR PASS uncached+cached scratch=%08x bytes=%u full_ddr=no "
               "ddr_passes=%u\r\n", (u32)(UINTPTR)scratch, (u32)sizeof scratch,
               stats.ddr_passes);

    if (timer_start() != G0_OK) fail(G0_TIMER, "SCU timer");
    xil_printf("G0 TIMER PASS interval_ms=50 ticks_per_second=20\r\n");
    xil_printf("G0 READY build=%s boot_mode=0x%02x net_init=no usb_init=no\r\n",
               G0_BUILD_ID, boot_mode);
    previous_ticks = ticks;
    XTime_GetTime(&previous_time);

    for (;;) {
        u32 current = ticks;
        XTime_GetTime(&now);
        if (current - previous_ticks > G0_TICKS_PER_SECOND + 1U) {
            stats.timer_errors++;
            fail(G0_TIMER, "tick gap");
        }
        if (now - previous_time >= COUNTS_PER_SECOND) {
            u32 elapsed_ticks = current - previous_ticks;
            if (elapsed_ticks < 18U || elapsed_ticks > 22U) {
                stats.timer_errors++;
                fail(G0_TIMER, "tick rate");
            }
            previous_ticks = current;
            previous_time = now;
            seconds++;
            if (seconds % 60U == 0U) {
                if (ddr_test(1) != G0_OK) {
                    stats.ddr_errors++;
                    xil_printf("G0 DDR FAIL uptime_s=%u\r\n", seconds);
                    fail(G0_DDR, "DDR periodic");
                }
            }
            if (seconds % 10U == 0U) {
                xil_printf("G0 STAT uptime_s=%u ticks=%u ddr_pass=%u ddr_err=%u "
                           "assert=%u exception=%u timer_err=%u boot_mode=0x%02x\r\n",
                           seconds, ticks, stats.ddr_passes, stats.ddr_errors,
                           stats.assertions, stats.exceptions, stats.timer_errors, boot_mode);
            }
        }
    }
}
