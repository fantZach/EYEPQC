/* G3: real OV5640 JPEG in DDR, fragmented through PL AES-GCM, volatile JTAG test. */
#include "xparameters.h"
#include "xaxidma.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xiltimer.h"
#include "xuartps.h"
#include "sleep.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define CAP_BASE 0x40400000U
#define CRYPTO_BASE 0x40410000U
#define CAM_GPIO 0x41200000U
#define DMA_GPIO 0x41210000U
#define GCM_BASE 0x43c00000U
#define MAGIC 0x33474345U
#define FRAME_CAP 65536U
#define CHUNK 1400U
#define SEALED_CAP 68096U
#define RX_BTT 1472U
#define GUARD 64U

struct g3_job {
    uint32_t magic, state, cfg, status, frame_length, chunks, sealed_length, elapsed_us;
    uint32_t frame_address, sealed_address, camera_status, cap_status;
    uint32_t tx_status, rx_status, pclk_hz, packet_count;
    uint8_t key[16], nonce_prefix[8];
    uint32_t requested_frames, completed_frames, total_bytes, dropped, overflows;
    uint32_t queued, sent, capture_us, encrypt_us, last_nonce_start;
};
volatile struct g3_job g3_job __attribute__((aligned(64)));
// ponytail: reuse one DDR pair; retain the last frame for host authentication.
// Add a ring only if every frame must remain available after a continuous run.
uint8_t g3_frame[FRAME_CAP + GUARD] __attribute__((aligned(64)));
uint8_t g3_sealed[SEALED_CAP] __attribute__((aligned(64)));
static XAxiDma capture, crypto;
_Static_assert(sizeof(struct g3_job) == 128 && offsetof(struct g3_job, key) == 64,
               "G3 mailbox ABI");

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
static void route(unsigned mode, int flush)
{
    Xil_Out32(DMA_GPIO, mode | (flush ? 4U : 0U));
}
static uint32_t stat(unsigned selector, unsigned mode, int flush)
{
    Xil_Out32(DMA_GPIO, mode | (flush ? 4U : 0U) | selector << 4);
    uint32_t value = Xil_In32(DMA_GPIO + 8);
    route(mode, flush);
    return value;
}
static int reset_dma(void)
{
    XTime start;
    XAxiDma_Reset(&capture);
    XAxiDma_Reset(&crypto);
    XTime_GetTime(&start);
    while (!XAxiDma_ResetIsDone(&capture) || !XAxiDma_ResetIsDone(&crypto))
        if (elapsed_us(start) > 100000U) return 1;
    return 0;
}
static int dma_error(XAxiDma *dma, unsigned direction)
{
    unsigned offset = direction == XAXIDMA_DMA_TO_DEVICE ? XAXIDMA_TX_OFFSET : XAXIDMA_RX_OFFSET;
    return XAxiDma_ReadReg(dma->RegBase, offset + XAXIDMA_SR_OFFSET) & XAXIDMA_IRQ_ERROR_MASK;
}
static int wait_dma(XAxiDma *dma, unsigned direction, unsigned limit_us)
{
    XTime start;
    XTime_GetTime(&start);
    while (XAxiDma_Busy(dma, direction)) {
        if (dma_error(dma, direction)) return 1;
        if (elapsed_us(start) > limit_us) return 2;
    }
    return dma_error(dma, direction) ? 1 : 0;
}
static void zeroize(void)
{
    Xil_Out32(GCM_BASE, 2);
    volatile uint8_t *p = g3_job.key;
    for (unsigned i = 0; i < 24; ++i) p[i] = 0;
}
static int configure_camera(unsigned cfg)
{
    if (reset_dma()) return 10;
    route(1, 1);
    Xil_Out32(CAM_GPIO, cfg | 0x80000000U); usleep(10000);
    Xil_Out32(CAM_GPIO, cfg | 1U); usleep(10); Xil_Out32(CAM_GPIO, cfg);
    XTime start;
    XTime_GetTime(&start);
    do {
        g3_job.camera_status = Xil_In32(CAM_GPIO + 8);
        if (g3_job.camera_status & 0x30000U) break;
        if (elapsed_us(start) > 5000000U) return 11;
    } while (1);
    if ((g3_job.camera_status & 0x30000U) != 0x10000U ||
        (g3_job.camera_status & 0xffffU) != 0x5640U ||
        !(g3_job.camera_status & 0x800000U) ||
        (g3_job.camera_status & 0x0f000000U)) return 12;
    uint32_t ticks = stat(7, 1, 1);
    XTime_GetTime(&start); usleep(100000);
    uint32_t edges = stat(7, 1, 1) - ticks;
    g3_job.pclk_hz = (uint32_t)((uint64_t)edges * 1000000U / elapsed_us(start));
    if (edges < 64U || g3_job.pclk_hz > 72000000U) return 13;
    route(1, 0);
    return 0;
}
static int capture_frame(void)
{
    memset(g3_frame, 0xa5, sizeof g3_frame);
    if (XAxiDma_SimpleTransfer(&capture, (UINTPTR)g3_frame, FRAME_CAP,
                               XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS ||
        wait_dma(&capture, XAXIDMA_DEVICE_TO_DMA, 3000000U)) return 14;
    g3_job.cap_status = XAxiDma_ReadReg(CAP_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    unsigned n = XAxiDma_ReadReg(CAP_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_BUFFLEN_OFFSET);
    if (n < 4 || n > FRAME_CAP || g3_frame[0] != 0xff || g3_frame[1] != 0xd8 ||
        g3_frame[n-2] != 0xff || g3_frame[n-1] != 0xd9) return 15;
    for (unsigned i = FRAME_CAP; i < sizeof g3_frame; ++i)
        if (g3_frame[i] != 0xa5) return 16;
    g3_job.frame_length = n;
    return 0;
}
static int encrypt_frame(unsigned *nonce_counter)
{
    unsigned n = g3_job.frame_length;
    unsigned chunks = (n + CHUNK - 1U) / CHUNK;
    if (*nonce_counter > UINT32_MAX - chunks) return 27;
    g3_job.last_nonce_start = *nonce_counter;
    unsigned cursor = 0;
    for (unsigned index = 0, offset = 0; offset < n; ++index) {
        unsigned size = n - offset < CHUNK ? n - offset : CHUNK;
        if (cursor + RX_BTT + GUARD > sizeof g3_sealed) return 20;
        memset(g3_sealed + cursor, 0xa5, RX_BTT + GUARD);
        Xil_Out32(GCM_BASE, 2);
        for (unsigned i = 0; i < 4; ++i)
            Xil_Out32(GCM_BASE + 0x20 + i*4, be32(g3_job.key + i*4));
        Xil_Out32(GCM_BASE + 0x30, be32(g3_job.nonce_prefix));
        Xil_Out32(GCM_BASE + 0x34, be32(g3_job.nonce_prefix + 4));
        Xil_Out32(GCM_BASE + 0x38, (*nonce_counter)++);
        Xil_Out32(GCM_BASE + 0x40, n);
        Xil_Out32(GCM_BASE + 0x44, offset);
        Xil_Out32(GCM_BASE + 0x48, index);
        Xil_Out32(GCM_BASE + 0x4c, chunks);
        Xil_Out32(GCM_BASE + 8, size);
        Xil_Out32(GCM_BASE + 12, 16);
        Xil_Out32(GCM_BASE, 1);
        if (XAxiDma_SimpleTransfer(&crypto, (UINTPTR)(g3_sealed + cursor), RX_BTT,
                                   XAXIDMA_DEVICE_TO_DMA) != XST_SUCCESS ||
            XAxiDma_SimpleTransfer(&crypto, (UINTPTR)(g3_frame + offset), size,
                                   XAXIDMA_DMA_TO_DEVICE) != XST_SUCCESS) return 21;
        XTime start;
        XTime_GetTime(&start);
        while (!(Xil_In32(GCM_BASE + 4) & 2U) ||
               XAxiDma_Busy(&crypto, XAXIDMA_DEVICE_TO_DMA) ||
               XAxiDma_Busy(&crypto, XAXIDMA_DMA_TO_DEVICE)) {
            if ((Xil_In32(GCM_BASE + 4) & 4U) ||
                dma_error(&crypto, XAXIDMA_DEVICE_TO_DMA) ||
                dma_error(&crypto, XAXIDMA_DMA_TO_DEVICE)) return 22;
            if (elapsed_us(start) > 500000U) return 23;
        }
        unsigned actual = XAxiDma_ReadReg(CRYPTO_BASE,
                              XAXIDMA_RX_OFFSET + XAXIDMA_BUFFLEN_OFFSET);
        g3_job.tx_status = XAxiDma_ReadReg(CRYPTO_BASE, XAXIDMA_TX_OFFSET + XAXIDMA_SR_OFFSET);
        g3_job.rx_status = XAxiDma_ReadReg(CRYPTO_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
        if (actual != size + 16U) return 24;
        for (unsigned i = actual; i < actual + GUARD; ++i)
            if (g3_sealed[cursor + i] != 0xa5) return 25;
        cursor += actual;
        offset += size;
    }
    g3_job.chunks = chunks;
    g3_job.sealed_length = cursor;
    g3_job.packet_count = Xil_In32(GCM_BASE + 0x10);
    return cursor == n + chunks*16U ? 0 : 26;
}
static unsigned run(void)
{
    unsigned cfg = g3_job.cfg;
    unsigned count = g3_job.requested_frames;
    if (g3_job.magic != MAGIC || !count || count > 1000U ||
        (cfg & ~0x01fffffeU) || !(cfg & 2U) ||
        (cfg >> 9) < 1000U || (cfg >> 9) > 5000U) return 1;
    g3_job.completed_frames = g3_job.total_bytes = g3_job.capture_us = g3_job.encrypt_us = 0;
    g3_job.dropped = g3_job.overflows = g3_job.queued = g3_job.sent = 0;
    unsigned status = configure_camera(cfg);
    unsigned nonce_counter = 0;
    XTime start, phase;
    XTime_GetTime(&start);
    for (unsigned frame = 0; frame < count && !status; ++frame) {
        XTime_GetTime(&phase);
        status = capture_frame();
        g3_job.capture_us += elapsed_us(phase);
        if (status) break;
        if (reset_dma()) { status = 17; break; }
        route(2, 0); // Keep DVP/FIFO live while PL encrypts the completed DDR frame.
        XTime_GetTime(&phase);
        status = encrypt_frame(&nonce_counter);
        g3_job.encrypt_us += elapsed_us(phase);
        if (status) break;
        g3_job.completed_frames++;
        g3_job.total_bytes += g3_job.frame_length;
        if (reset_dma()) { status = 28; break; }
        route(1, 0);
        if (frame % 100U == 0) xil_printf("G3 LIVE frame=%u bytes=%u\r\n", frame, g3_job.frame_length);
    }
    g3_job.elapsed_us = elapsed_us(start);
    // Snapshot live counters before the final flush resets M04 statistics.
    if (!status) {
        g3_job.queued = stat(1, 1, 0);
        g3_job.dropped = stat(2, 1, 0);
        g3_job.overflows = stat(3, 1, 0);
        g3_job.sent = stat(5, 1, 0);
    }
    route(1, 1);
    if (!status && reset_dma()) status = 29;
    g3_job.frame_address = (uint32_t)(UINTPTR)g3_frame;
    g3_job.sealed_address = (uint32_t)(UINTPTR)g3_sealed;
    return status;
}
int main(void)
{
    XUartPs uart;
    XUartPs_Config *cfg = XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
    Xil_DCacheDisable();
    if (!cfg || XUartPs_CfgInitialize(&uart, cfg, cfg->BaseAddress) ||
        XUartPs_SetBaudRate(&uart, 115200)) return 1;
    usleep(1);
    Xil_Out32(CAM_GPIO + 4, 0); Xil_Out32(CAM_GPIO + 12, 0xffffffffU);
    Xil_Out32(DMA_GPIO + 4, 0); Xil_Out32(DMA_GPIO + 12, 0xffffffffU);
    route(1, 1);
    XAxiDma_Config *cc = XAxiDma_LookupConfig(CAP_BASE);
    XAxiDma_Config *dc = XAxiDma_LookupConfig(CRYPTO_BASE);
    if (stat(0, 1, 1) != 0x4d303531U || !cc || !dc ||
        XAxiDma_CfgInitialize(&capture, cc) != XST_SUCCESS ||
        XAxiDma_CfgInitialize(&crypto, dc) != XST_SUCCESS ||
        XAxiDma_HasSg(&capture) || XAxiDma_HasSg(&crypto) ||
        Xil_In32(GCM_BASE + 0x14) != 0x47434d31U) return 2;
    XAxiDma_IntrDisable(&capture, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DEVICE_TO_DMA);
    XAxiDma_IntrDisable(&crypto, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DEVICE_TO_DMA);
    XAxiDma_IntrDisable(&crypto, XAXIDMA_IRQ_ALL_MASK, XAXIDMA_DMA_TO_DEVICE);
    if (reset_dma()) return 3;
    g3_job.magic = MAGIC;
    g3_job.frame_address = (uint32_t)(UINTPTR)g3_frame;
    g3_job.sealed_address = (uint32_t)(UINTPTR)g3_sealed;
    xil_printf("G3 READY mailbox=%08x frame=%08x sealed=%08x\r\n",
        (unsigned)(UINTPTR)&g3_job, g3_job.frame_address, g3_job.sealed_address);
    for (;;) if (g3_job.state == 1) {
        g3_job.state = 4;
        g3_job.status = run();
        zeroize();
        route(2, 1);
        if (g3_job.status && reset_dma()) g3_job.status = 30;
        __asm__ volatile("dsb sy" ::: "memory");
        g3_job.state = g3_job.status ? 3 : 2;
        xil_printf("G3 JOB status=%u frame=%u chunks=%u sealed=%u us=%u\r\n",
            g3_job.status, g3_job.frame_length, g3_job.chunks,
            g3_job.sealed_length, g3_job.elapsed_us);
    }
}
