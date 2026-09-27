/* M01 only: Standalone + lwIP RAW, one shared SDT interrupt controller. */
#include "xparameters.h"
#include "xil_assert.h"
#include "xil_cache.h"
#include "xil_exception.h"
#include "xil_printf.h"
#include "xil_testmem.h"
#include "xinterrupt_wrap.h"
#include "xiltimer.h"
#include "xscutimer.h"
#include "xuartps.h"
#include "lwip/init.h"
#include "lwip/tcp.h"
#include "lwip/priv/tcp_priv.h"
#include "lwip/etharp.h"
#include "netif/xadapter.h"

#if !NO_SYS || !NO_SYS_NO_TIMERS || LWIP_DHCP || LWIP_IPV6
#error "M01 requires RAW IPv4, static IP and manually serviced lwIP timers"
#endif

enum m01_status {
    M01_OK, M01_UART, M01_DDR, M01_TIMER, M01_NETWORK, M01_ASSERT, M01_EXCEPTION
};
static struct {
    u32 ddr_passes, ddr_errors, connections, accepted, echo_bytes, network_errors;
    u32 assertions, exceptions, timer_lag;
} stats;
static volatile u32 ticks;
static XScuTimer timer;
/* Owned BSS scratch: never test arbitrary DDR addresses over code/stack/lwIP. */
static u32 scratch[16384] __attribute__((aligned(64)));
static unsigned char echo_buffer[TCP_WND];

static void fatal(enum m01_status code, const char *where)
{
    Xil_ExceptionDisable();
    xil_printf("M01 FAIL code=%u where=%s ticks=%u\r\n", code, where, ticks);
    for (;;) { /* Keep evidence; do not silently reset after a fault. */ }
}

static void assertion(const char8 *file, s32 line)
{
    stats.assertions++;
    xil_printf("ASSERT %s:%d\r\n", file, line);
    fatal(M01_ASSERT, "assert");
}
#define M01_ASSERT(condition) do { \
    if (!(condition)) assertion(__FILE__, __LINE__); \
} while (0) /* Always enabled, including Release/NDEBUG BSP builds. */

static void exception(void *id)
{
    stats.exceptions++;
    xil_printf("EXCEPTION id=%u\r\n", (u32)(UINTPTR)id);
    fatal(M01_EXCEPTION, "exception");
}

static int ddr_test(int cached)
{
    u32 i;
    volatile u32 *memory = scratch;
    if (!cached && Xil_TestMem32(scratch, 16384, 0xA5A55A5AU,
                                XIL_TESTMEM_ALLMEMTESTS) != XST_SUCCESS) {
        return M01_DDR;
    }
    /* Cached test must reach DDR, not merely read back dirty cache lines. */
    for (i = 0; i < 16384; ++i) memory[i] = i ^ 0xA5A55A5AU;
    if (cached) {
        Xil_DCacheFlushRange((INTPTR)scratch, sizeof scratch);
        Xil_DCacheInvalidateRange((INTPTR)scratch, sizeof scratch);
    }
    for (i = 0; i < 16384; ++i) {
        if (memory[i] != (i ^ 0xA5A55A5AU)) return M01_DDR;
    }
    stats.ddr_passes++;
    return M01_OK;
}

static void timer_irq(void *instance)
{
    XScuTimer *t = instance;
    if (XScuTimer_IsExpired(t)) {
        XScuTimer_ClearInterruptStatus(t);
        ticks++;
    }
}

static int timer_start(void)
{
    XScuTimer_Config *cfg = XScuTimer_LookupConfig(XPAR_XSCUTIMER_0_BASEADDR);
    if (!cfg || XScuTimer_CfgInitialize(&timer, cfg, cfg->BaseAddr) != XST_SUCCESS ||
        XScuTimer_SelfTest(&timer) != XST_SUCCESS) return M01_TIMER;
    XScuTimer_SetPrescaler(&timer, 0);
    /* Cortex-A9 private timer runs at CPU/2; 50 ms interval. */
    XScuTimer_LoadTimer(&timer, XPAR_CPU_CORE_CLOCK_FREQ_HZ / 40U);
    XScuTimer_EnableAutoReload(&timer);
    if (XSetupInterruptSystem(&timer, (void *)timer_irq, cfg->IntrId,
                              cfg->IntrParent, XINTERRUPT_DEFAULT_PRIORITY) != XST_SUCCESS)
        return M01_TIMER;
    XScuTimer_EnableInterrupt(&timer);
    XScuTimer_Start(&timer);
    return M01_OK;
}

static void echo_error(void *arg, err_t error)
{
    (void)arg;
    (void)error;
    M01_ASSERT(stats.connections > 0);
    stats.connections--;
    stats.network_errors++;
}

static err_t echo_recv(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t error);
static err_t echo_poll(void *arg, struct tcp_pcb *pcb);

static err_t echo_close(void *arg, struct tcp_pcb *pcb)
{
    err_t error;
    (void)arg;
    tcp_recv(pcb, NULL);
    tcp_poll(pcb, NULL, 0);
    tcp_err(pcb, NULL); /* A later reset of FIN_WAIT must not decrement twice. */
    error = tcp_close(pcb);
    if (error == ERR_OK) stats.connections--;
    else {
        tcp_recv(pcb, echo_recv);
        tcp_poll(pcb, echo_poll, 2);
        tcp_err(pcb, echo_error);
        tcp_arg(pcb, (void *)1); /* FIN may need retry when send queue is full. */
    }
    return error;
}

static err_t echo_poll(void *arg, struct tcp_pcb *pcb)
{
    if (arg) return echo_close(arg, pcb);
    (void)tcp_output(pcb);
    return ERR_OK;
}

static err_t echo_recv(void *arg, struct tcp_pcb *pcb, struct pbuf *p, err_t error)
{
    if (!p) return echo_close(arg, pcb);
    if (error != ERR_OK || p->tot_len > sizeof echo_buffer) {
        pbuf_free(p);
        tcp_abort(pcb); /* echo_error releases the connection counter. */
        return ERR_ABRT;
    }
    if (tcp_sndbuf(pcb) < p->tot_len) return ERR_MEM; /* lwIP retains/retries p. */
    M01_ASSERT(pbuf_copy_partial(p, echo_buffer, p->tot_len, 0) == p->tot_len);
    /* One atomic write: never echo a partial chain then duplicate it on retry. */
    error = tcp_write(pcb, echo_buffer, p->tot_len, TCP_WRITE_FLAG_COPY);
    if (error != ERR_OK) {
        stats.network_errors++;
        return error;
    }
    tcp_recved(pcb, p->tot_len);
    stats.echo_bytes += p->tot_len;
    pbuf_free(p);
    (void)tcp_output(pcb); /* Already queued; TCP ACK/timer/poll retries output. */
    return ERR_OK;
}

static err_t echo_accept(void *arg, struct tcp_pcb *pcb, err_t error)
{
    (void)arg;
    /* ponytail: four clients suffice for board bring-up; M11 owns the real service. */
    if (error != ERR_OK || stats.connections >= 4) {
        tcp_abort(pcb);
        return ERR_ABRT;
    }
    stats.connections++;
    stats.accepted++;
    tcp_recv(pcb, echo_recv);
    tcp_err(pcb, echo_error);
    tcp_poll(pcb, echo_poll, 2);
    return ERR_OK;
}

static int echo_start(void)
{
    struct tcp_pcb *pcb = tcp_new_ip_type(IPADDR_TYPE_V4);
    struct tcp_pcb *listener;
    if (!pcb) return M01_NETWORK;
    if (tcp_bind(pcb, IP_ANY_TYPE, 7) != ERR_OK) {
        tcp_abort(pcb);
        return M01_NETWORK;
    }
    listener = tcp_listen(pcb);
    if (!listener) {
        tcp_abort(pcb);
        return M01_NETWORK;
    }
    tcp_accept(listener, echo_accept);
    return M01_OK;
}

int main(void)
{
    XUartPs uart;
    XUartPs_Config *uart_cfg = XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
    struct netif netif;
    ip_addr_t ip, mask, gateway;
    unsigned char mac[] = {0x02, 0x00, 0x00, 0x00, 0x01, 0x10};
    XTime now, last;
    u32 serviced = 0, seconds = 0, previous_ticks = 0;
    int code;
    Xil_AssertSetCallback(assertion);
    if (!uart_cfg || XUartPs_CfgInitialize(&uart, uart_cfg, uart_cfg->BaseAddress) != XST_SUCCESS ||
        XUartPs_SetBaudRate(&uart, 115200) != XST_SUCCESS) fatal(M01_UART, "UART0");
    xil_printf("\r\nM01 BOOT cpu_hz=%u FCLK0=100000000 UART=115200\r\n",
               XPAR_CPU_CORE_CLOCK_FREQ_HZ);
    Xil_DCacheDisable();
    code = ddr_test(0);
    Xil_DCacheEnable();
    if (code == M01_OK) code = ddr_test(1);
    if (code != M01_OK) { stats.ddr_errors++; fatal(M01_DDR, "DDR boot"); }
    xil_printf("DDR PASS uncached+cached scratch=%08x bytes=%u (not full DDR)\r\n",
               (u32)(UINTPTR)scratch, (u32)sizeof scratch);
    code = timer_start();
    if (code != M01_OK) fatal(M01_TIMER, "SCU timer");
    lwip_init();
    IP4_ADDR(&ip, 192, 168, 1, 10);
    IP4_ADDR(&mask, 255, 255, 255, 0);
    IP4_ADDR(&gateway, 192, 168, 1, 1);
    if (!xemac_add(&netif, &ip, &mask, &gateway, mac, XPAR_XEMACPS_0_BASEADDR))
        fatal(M01_NETWORK, "GEM0");
    netif_set_default(&netif);
    netif_set_up(&netif);
    /* Register after SDT timer/GEM setup; do not create a second GIC instance. */
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_UNDEFINED_INT, exception, (void *)1);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_SWI_INT, exception, (void *)2);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_PREFETCH_ABORT_INT, exception, (void *)3);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_DATA_ABORT_INT, exception, (void *)4);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_FIQ_INT, exception, (void *)6);
    if (echo_start() != M01_OK) fatal(M01_NETWORK, "TCP port 7");
    xil_printf("ECHO READY 192.168.1.10:7 MAC=02:00:00:00:01:10\r\n");
    serviced = ticks; /* PHY negotiation during xemac_add can take seconds. */
    previous_ticks = serviced;
    XTime_GetTime(&last);
    for (;;) {
        u32 current = ticks;
        if (current - serviced > 20U) {
            stats.timer_lag++;
            fatal(M01_TIMER, "main loop stalled >1s");
        }
        while (serviced != current) {
            serviced++;
            if (serviced % 5U == 0) tcp_fasttmr();
            if (serviced % 10U == 0) tcp_slowtmr();
            if (serviced % 100U == 0) etharp_tmr();
        }
        (void)xemacif_input(&netif);
        XTime_GetTime(&now);
        if (now - last >= COUNTS_PER_SECOND) {
            u32 elapsed_ticks = current - previous_ticks;
            if (elapsed_ticks < 18 || elapsed_ticks > 22) fatal(M01_TIMER, "tick rate");
            previous_ticks = current;
            last = now;
            seconds++;
            eth_link_detect(&netif);
            if (seconds % 60U == 0) {
                if (ddr_test(1) != M01_OK) { stats.ddr_errors++; fatal(M01_DDR, "DDR periodic"); }
            }
            if (seconds % 10U == 0) {
                xil_printf("M01 STAT sec=%u ticks=%u ddr_pass=%u ddr_err=%u active=%u "
                           "accepted=%u echo_bytes=%u net_err=%u assert=%u except=%u lag=%u link=%u\r\n",
                           seconds, current, stats.ddr_passes, stats.ddr_errors, stats.connections,
                           stats.accepted, stats.echo_bytes, stats.network_errors, stats.assertions,
                           stats.exceptions, stats.timer_lag, netif_is_link_up(&netif));
            }
        }
    }
}
