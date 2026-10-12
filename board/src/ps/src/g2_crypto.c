/* G2: volatile JTAG mailbox -> native AXI DMA -> PL AES-GCM -> owned DDR. */
#include "xparameters.h"
#include "xaxidma.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xiltimer.h"
#include "xuartps.h"
#include "sleep.h"
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define DMA_BASE 0x40410000U
#define GCM_BASE 0x43c00000U
#define MAGIC 0x32474345U /* ECG2 */
#define TX_CAP 1472U
#define RX_CAP 1472U
#define GUARD 64U
#define LIMIT_US 500000U

struct g2_job {
    uint32_t magic, state, length, aad_length, status, actual, elapsed_us, packet_count;
    uint8_t key[16], nonce[12], aad[64], tag[16];
    uint32_t tx_address, rx_address, tx_status, rx_status;
    uint8_t reserved[36];
};
volatile struct g2_job g2_job __attribute__((aligned(64)));
uint8_t g2_tx[TX_CAP] __attribute__((aligned(64)));
uint8_t g2_rx[RX_CAP + GUARD] __attribute__((aligned(64)));
static XAxiDma dma;
_Static_assert(sizeof(struct g2_job) == 192, "mailbox ABI");
_Static_assert(offsetof(struct g2_job, key) == 32 && offsetof(struct g2_job, tag) == 124,
               "mailbox byte offsets");

static unsigned elapsed_us(XTime start)
{
    XTime now;
    XTime_GetTime(&now);
    return (unsigned)((now - start) / (COUNTS_PER_SECOND / 1000000U));
}
static uint32_t be32(const volatile uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}
static void clear_secret(void)
{
    volatile uint8_t *p = g2_job.key;
    for (unsigned i = 0; i < 16 + 12 + 64; i++) p[i] = 0;
}
static int reset_dma(void)
{
    XAxiDma_Reset(&dma);
    XTime start;
    XTime_GetTime(&start);
    while (!XAxiDma_ResetIsDone(&dma))
        if (elapsed_us(start) >= 100000U) return 1;
    return 0;
}
static unsigned run(void)
{
    unsigned length = g2_job.length, aad_length = g2_job.aad_length;
    if (length > 1400 || aad_length > 64) return 1;
    Xil_Out32(GCM_BASE, 2); // Abort/zeroize before loading each independent test key.
    for (unsigned i = 0; i < 4; i++) Xil_Out32(GCM_BASE + 0x20 + i*4, be32(g2_job.key + i*4));
    for (unsigned i = 0; i < 3; i++) Xil_Out32(GCM_BASE + 0x30 + i*4, be32(g2_job.nonce + i*4));
    for (unsigned i = 0; i < 16; i++) Xil_Out32(GCM_BASE + 0x40 + i*4, be32(g2_job.aad + i*4));
    Xil_Out32(GCM_BASE + 8, length);
    Xil_Out32(GCM_BASE + 12, aad_length);
    memset(g2_rx, 0xa5, sizeof g2_rx);
    XTime start;
    XTime_GetTime(&start);
    Xil_Out32(GCM_BASE, 1);
    if (length && XAxiDma_SimpleTransfer(&dma, (UINTPTR)g2_tx, length,
                                          XAXIDMA_DMA_TO_DEVICE) != XST_SUCCESS) return 3;
    usleep(1000); // Arm S2MM late: real M_AXIS TREADY backpressure, then release it.
    if (XAxiDma_SimpleTransfer(&dma, (UINTPTR)g2_rx, RX_CAP,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS) return 4;
    while (1) {
        uint32_t status = Xil_In32(GCM_BASE + 4);
        uint32_t tx_status = XAxiDma_ReadReg(DMA_BASE, XAXIDMA_TX_OFFSET + XAXIDMA_SR_OFFSET);
        uint32_t rx_status = XAxiDma_ReadReg(DMA_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
        if ((status & 4U) || (tx_status & XAXIDMA_IRQ_ERROR_MASK) ||
            (rx_status & XAXIDMA_IRQ_ERROR_MASK)) return 5;
        if ((status & 2U) && !XAxiDma_Busy(&dma, XAXIDMA_DEVICE_TO_DMA) &&
            (!length || !XAxiDma_Busy(&dma, XAXIDMA_DMA_TO_DEVICE))) break;
        if (elapsed_us(start) > LIMIT_US) return 6;
    }
    g2_job.elapsed_us = elapsed_us(start);
    g2_job.actual = XAxiDma_ReadReg(DMA_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_BUFFLEN_OFFSET);
    g2_job.tx_status = XAxiDma_ReadReg(DMA_BASE, XAXIDMA_TX_OFFSET + XAXIDMA_SR_OFFSET);
    g2_job.rx_status = XAxiDma_ReadReg(DMA_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    g2_job.packet_count = Xil_In32(GCM_BASE + 0x10);
    for (unsigned i = 0; i < 4; i++) {
        uint32_t word = Xil_In32(GCM_BASE + 0x80 + i*4);
        for (unsigned j = 0; j < 4; j++) g2_job.tag[i*4+j] = (uint8_t)(word >> (24-j*8));
    }
    if (g2_job.actual != length + 16 || g2_job.packet_count == 0) return 7;
    for (unsigned i = g2_job.actual; i < g2_job.actual + GUARD; i++)
        if (g2_rx[i] != 0xa5) return 8;
    for (unsigned i = RX_CAP; i < sizeof g2_rx; i++)
        if (g2_rx[i] != 0xa5) return 9;
    return 0;
}
int main(void)
{
    XUartPs uart;
    XUartPs_Config *cfg = XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
    Xil_DCacheDisable();
    if (!cfg || XUartPs_CfgInitialize(&uart, cfg, cfg->BaseAddress) ||
        XUartPs_SetBaudRate(&uart, 115200)) return 1;
    usleep(1); // Native xiltimer lazily starts and resets the global counter.
    XAxiDma_Config *dcfg = XAxiDma_LookupConfig(DMA_BASE);
    if (!dcfg || XAxiDma_CfgInitialize(&dma, dcfg) != XST_SUCCESS || XAxiDma_HasSg(&dma)) return 2;
    XAxiDma_IntrDisable(&dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DMA_TO_DEVICE);
    XAxiDma_IntrDisable(&dma, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DEVICE_TO_DMA);
    if (reset_dma()) return 3;
    g2_job.magic = MAGIC;
    g2_job.tx_address = (uint32_t)(UINTPTR)g2_tx;
    g2_job.rx_address = (uint32_t)(UINTPTR)g2_rx;
    xil_printf("G2 READY mailbox=%08x tx=%08x rx=%08x\r\n",
        (unsigned)(UINTPTR)&g2_job, g2_job.tx_address, g2_job.rx_address);
    for (;;) if (g2_job.state == 1) {
        g2_job.state = 4;
        g2_job.status = run();
        Xil_Out32(GCM_BASE, 2);
        clear_secret();
        if (g2_job.status && reset_dma()) g2_job.status = 10;
        __asm__ volatile("dsb sy" ::: "memory");
        g2_job.state = g2_job.status ? 3 : 2;
        xil_printf("G2 JOB status=%u bytes=%u count=%u us=%u\r\n",
            g2_job.status, g2_job.actual, g2_job.packet_count, g2_job.elapsed_us);
    }
}
