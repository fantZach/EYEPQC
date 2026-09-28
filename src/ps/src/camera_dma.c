/* M05: native simple DMA/IRQ drivers; JTAG only reads a completed owned DDR frame. */
#include "xparameters.h"
#include "xaxidma.h"
#include "xinterrupt_wrap.h"
#include "xil_cache.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xiltimer.h"
#include "xuartps.h"
#include "sleep.h"
#include "dma_buffers.h"
#include <stddef.h>
#include <string.h>

#define CAP_BASE 0x40400000U
#define CRYPTO_BASE 0x40410000U
#define CAM_GPIO 0x41200000U
#define DMA_GPIO 0x41210000U
#define MAGIC 0x35414d44U
#define RX XAXIDMA_DEVICE_TO_DMA
#define TX XAXIDMA_DMA_TO_DEVICE
#define GUARD 64U
struct dma_job {
    uint32_t magic, state, command, count, cache, status, completed, bytes;
    uint32_t checksum, elapsed_us, rx_irq, tx_irq, error_irq, timeouts, resets, held_rejects;
    uint32_t address, length, frames, queued, dropped, overflows, peak, sent;
    uint32_t camera_status, pclk_hz, max_length, cap_status, tx_status, crypto_status, stalls, reserved;
};
volatile struct dma_job dma_job __attribute__((aligned(64)));
uint8_t dma_frames[2][DMA_FRAME_CAPACITY + GUARD] __attribute__((aligned(64)));
uint8_t dma_packet[DMA_FRAME_CAPACITY + GUARD] __attribute__((aligned(64)));
static uint8_t pattern[DMA_FRAME_CAPACITY] __attribute__((aligned(64)));
static struct dma_buffer slots[2], packet;
static XAxiDma capture, crypto;
struct channel { XAxiDma *dma; int direction; volatile unsigned done, error, interrupts; };
static struct channel cap = {&capture, RX, 0, 0, 0};
static struct channel tx = {&crypto, TX, 0, 0, 0};
static struct channel out = {&crypto, RX, 0, 0, 0};
static uint32_t route_cfg = 4;
static int held = -1;
_Static_assert(sizeof(struct dma_job) == 128, "mailbox ABI");
_Static_assert(offsetof(struct dma_job, address) == 64, "payload address ABI");
_Static_assert((DMA_FRAME_CAPACITY + GUARD) % 64 == 0, "no shared cache lines");

static unsigned elapsed_us(XTime start)
{
    XTime now;
    XTime_GetTime(&now);
    return (unsigned)((now - start) / (COUNTS_PER_SECOND / 1000000U));
}
static void irq(void *arg)
{
    struct channel *c = arg;
    unsigned bits = XAxiDma_IntrGetIrq(c->dma, c->direction);
    XAxiDma_IntrAckIrq(c->dma, bits, c->direction);
    c->interrupts++;
    if (bits & XAXIDMA_IRQ_ERROR_MASK) { c->error = bits; dma_job.error_irq++; }
    if (bits & XAXIDMA_IRQ_IOC_MASK) c->done = 1;
}
static void enable_irqs(void)
{
    XAxiDma_IntrEnable(&capture, XAXIDMA_IRQ_ALL_MASK, RX);
    XAxiDma_IntrEnable(&crypto, XAXIDMA_IRQ_ALL_MASK, TX);
    XAxiDma_IntrEnable(&crypto, XAXIDMA_IRQ_ALL_MASK, RX);
}
static void dump(void)
{
    dma_job.cap_status = XAxiDma_ReadReg(CAP_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    dma_job.tx_status = XAxiDma_ReadReg(CRYPTO_BASE, XAXIDMA_TX_OFFSET + XAXIDMA_SR_OFFSET);
    dma_job.crypto_status = XAxiDma_ReadReg(CRYPTO_BASE, XAXIDMA_RX_OFFSET + XAXIDMA_SR_OFFSET);
    xil_printf("DMA STATUS cap=%08x tx=%08x crypto=%08x irq_error=%u timeout=%u\r\n",
        dma_job.cap_status, dma_job.tx_status, dma_job.crypto_status,
        dma_job.error_irq, dma_job.timeouts);
}
static int reset_dma(void)
{
    XTime start;
    XAxiDma_Reset(&capture);
    XAxiDma_Reset(&crypto);
    XTime_GetTime(&start);
    while (!XAxiDma_ResetIsDone(&capture) || !XAxiDma_ResetIsDone(&crypto))
        if (elapsed_us(start) > 100000) return 1;
    cap.done = tx.done = out.done = cap.error = tx.error = out.error = 0;
    dma_job.resets++;
    dma_buffers_abort(slots); // Never frees READY/ENCRYPTING/SENDING.
    if (packet.owner == DMA_CAPTURING) { packet.owner = DMA_FREE; packet.length = 0; }
    enable_irqs();
    return 0;
}
static int init_dma(XAxiDma *dma, UINTPTR base)
{
    XAxiDma_Config *cfg = XAxiDma_LookupConfig(base);
    if (!cfg || XAxiDma_CfgInitialize(dma, cfg) != XST_SUCCESS || XAxiDma_HasSg(dma)) return 1;
    xil_printf("DMA CONFIG base=%08x irq0=%04x irq1=%04x parent=%08x\r\n",
        (unsigned)base, cfg->IntrId[0], cfg->IntrId[1], (unsigned)cfg->IntrParent);
    if (base == CAP_BASE)
        // SDT packs connected interrupts: S2MM-only DMA's RX interrupt is array entry zero.
        return XSetupInterruptSystem(&cap, irq, cfg->IntrId[0], cfg->IntrParent, XINTERRUPT_DEFAULT_PRIORITY);
    if (XSetupInterruptSystem(&tx, irq, cfg->IntrId[0], cfg->IntrParent, XINTERRUPT_DEFAULT_PRIORITY)) return 1;
    return XSetupInterruptSystem(&out, irq, cfg->IntrId[1], cfg->IntrParent, XINTERRUPT_DEFAULT_PRIORITY);
}
static void route(unsigned mode, int flush)
{
    route_cfg = mode | (flush ? 4U : 0U);
    Xil_Out32(DMA_GPIO, route_cfg);
}
static uint32_t stat(unsigned selector)
{
    Xil_Out32(DMA_GPIO, route_cfg | selector << 4);
    uint32_t value = Xil_In32(DMA_GPIO + 8);
    Xil_Out32(DMA_GPIO, route_cfg);
    return value;
}
static int wait_done(struct channel *rx, int with_tx, unsigned limit_us)
{
    XTime start;
    XTime_GetTime(&start);
    while (!rx->done || (with_tx && !tx.done)) {
        if (rx->error || (with_tx && tx.error)) return 1;
        if (elapsed_us(start) > limit_us) { dma_job.timeouts++; return 2; }
    }
    __asm__ volatile("dsb sy" ::: "memory");
    return rx->error || (with_tx && tx.error) ? 1 : 0;
}
static int receive(struct channel *rx, uint8_t *data, unsigned expected)
{
    rx->done = rx->error = 0;
    unsigned prefix = expected < DMA_FRAME_CAPACITY - GUARD ? expected + GUARD : DMA_FRAME_CAPACITY;
    memset(data, 0xa5, prefix);
    memset(data + DMA_FRAME_CAPACITY, 0xa5, GUARD);
    // Clean BEFORE device writes. Never clean stale dirty RX lines AFTER completion.
    Xil_DCacheFlushRange((UINTPTR)data, prefix);
    Xil_DCacheFlushRange((UINTPTR)(data + DMA_FRAME_CAPACITY), GUARD);
    return XAxiDma_SimpleTransfer(rx->dma, (UINTPTR)data, DMA_FRAME_CAPACITY, RX);
}
static uint32_t received(struct channel *rx, uint8_t *data)
{
    uint32_t n = XAxiDma_ReadReg(rx->dma->RegBase, XAXIDMA_RX_OFFSET + XAXIDMA_BUFFLEN_OFFSET);
    Xil_DCacheInvalidateRange((UINTPTR)data, DMA_FRAME_CAPACITY + GUARD);
    if (!n || n > DMA_FRAME_CAPACITY) return 0;
    for (unsigned i = 0; i < GUARD; i++) if (data[DMA_FRAME_CAPACITY + i] != 0xa5) return 0;
    return n;
}
static int send(UINTPTR address, uint32_t length)
{
    tx.done = tx.error = 0;
    return XAxiDma_SimpleTransfer(&crypto, address, length, TX);
}
static uint32_t hash(const uint8_t *data, unsigned n)
{
    uint32_t h = 2166136261U;
    for (unsigned i = 0; i < n; i++) h = (h ^ data[i]) * 16777619U;
    return h;
}
static int release_held(void)
{
    if (held < 0) return 0;
    if (dma_buffer_advance(&slots[held], DMA_FREE)) return 1;
    held = -1; dma_job.address = dma_job.length = 0;
    return 0;
}

static int transfer(unsigned iteration, unsigned mode)
{
    static const unsigned edges[] = {1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,
        1023,1024,1025,65533,65534,65535,65536};
    unsigned edge = iteration % 128U;
    unsigned n = edge < sizeof edges / sizeof *edges ? edges[edge] :
        (iteration % 257 == 0 ? DMA_FRAME_CAPACITY : (iteration * 1103515245U + 12345U) % 4096U + 1U);
    struct channel *rx = mode == 0 ? &cap : &out;
    int index = -1;
    uint8_t *data = dma_packet;
    uint32_t held_hash = held < 0 ? 0 : hash(dma_frames[held], slots[held].length);
    // Reset only on route changes: thousands of consecutive transfers also reuse the channels.
    if ((route_cfg & 3U) != mode) {
        if (reset_dma()) return 10;
        route(mode, 1);
    }
    if (!mode) {
        index = dma_buffer_begin(slots);
        if (index < 0) return 11;
        data = dma_frames[index];
        if (held >= 0) {
            if (dma_buffer_begin(slots) != -1) return 12;
            dma_job.held_rejects++;
        }
    } else {
        if (packet.owner != DMA_FREE) return 13;
        packet.owner = DMA_CAPTURING;
    }
    for (unsigned i = 0; i < n; i++) pattern[i] = (uint8_t)(i * 17U + iteration * 13U);
    Xil_DCacheFlushRange((UINTPTR)pattern, n);
    // Starting TX first exercises native stream backpressure before S2MM is armed.
    if (send((UINTPTR)pattern, n)) return 14;
    usleep(20);
    if (receive(rx, data, n) || wait_done(rx, 1, 100000)) { dump(); return 15; }
    unsigned actual = received(rx, data);
    if (actual != n || memcmp(data, pattern, n)) return 16;
    // Also check the unwritten tail adjacent to the variable TLAST.
    for (unsigned i = n; i < n + GUARD && i < DMA_FRAME_CAPACITY; i++) if (data[i] != 0xa5) return 17;
    if (held >= 0 && held_hash != hash(dma_frames[held], slots[held].length)) return 18;
    dma_job.checksum ^= hash(data, n);
    dma_job.completed++; dma_job.bytes += n;
    if (n > dma_job.max_length) dma_job.max_length = n;
    if (!mode) {
        if (dma_buffer_complete(&slots[index], n) || release_held() ||
            dma_buffer_advance(&slots[index], DMA_SENDING)) return 19;
        held = index;
    } else {
        if (dma_buffer_complete(&packet, n) || dma_buffer_advance(&packet, DMA_ENCRYPTING) ||
            dma_buffer_advance(&packet, DMA_SENDING) || dma_buffer_advance(&packet, DMA_FREE)) return 20;
        // ENCRYPTING is only an ownership test here; this route does not encrypt.
    }
    return 0;
}
static int recovery_tests(void)
{
    if (reset_dma()) return 30;
    route(0, 1);
    int index = dma_buffer_begin(slots);
    if (index < 0 || receive(&cap, dma_frames[index], 64)) return 31;
    if (wait_done(&cap, 0, 2000) != 2) return 32; // RX armed with deliberately no source.
    dump();
    if (reset_dma() || slots[index].owner != DMA_FREE) return 33;
    if (transfer(3, 0)) return 34;
    if (reset_dma()) return 35;
    route(0, 1);
    index = dma_buffer_begin(slots);
    if (index < 0 || receive(&cap, dma_frames[index], 64)) return 36;
    // Read-only decode-error injection beyond the PS HP DDR window. RX stays in owned RAM.
    unsigned before = dma_job.error_irq;
    if (send(0x40000000U, 64) || wait_done(&cap, 1, 100000) != 1 || !tx.error ||
        dma_job.error_irq == before) { dump(); return 37; }
    dump();
    if (reset_dma() || slots[index].owner != DMA_FREE || transfer(4, 2)) return 38;
    return release_held();
}
static int camera_frames(unsigned count, unsigned cfg)
{
    XTime start;
    if (reset_dma()) return 40;
    route(1, 1); // Hold through sensor restart; a short pulse with PCLK stopped cannot flush XPM.
    Xil_Out32(CAM_GPIO, cfg | 0x80000000U); usleep(10000);
    Xil_Out32(CAM_GPIO, cfg | 1U); usleep(10); Xil_Out32(CAM_GPIO, cfg);
    XTime_GetTime(&start);
    do {
        dma_job.camera_status = Xil_In32(CAM_GPIO + 8);
        if (dma_job.camera_status & 0x30000U) break;
        if (elapsed_us(start) > 5000000) return 41;
    } while (1);
    if ((dma_job.camera_status & 0x30000U) != 0x10000U ||
        (dma_job.camera_status & 0xffffU) != 0x5640U || !(dma_job.camera_status & 0x800000U) ||
        (dma_job.camera_status & 0x0f000000U)) return 42;
    uint32_t ticks = stat(7);
    XTime_GetTime(&start); usleep(100000);
    uint32_t edges = stat(7) - ticks;
    // This is a window-average edge rate; JPEG PCLK may pause during blanking.
    dma_job.pclk_hz = (uint32_t)((uint64_t)edges * 1000000U / elapsed_us(start));
    if (edges < 64U || dma_job.pclk_hz > 72000000U) return 43;
    route(1, 0);
    for (unsigned run = 0; run < count; run++) {
        int index = dma_buffer_begin(slots);
        if (index < 0) return 44;
        if (held >= 0) {
            if (dma_buffer_begin(slots) != -1) return 45;
            dma_job.held_rejects++;
        }
        uint32_t previous_hash = held < 0 ? 0 : hash(dma_frames[held], slots[held].length);
        if (receive(&cap, dma_frames[index], DMA_FRAME_CAPACITY) || wait_done(&cap, 0, 3000000)) { dump(); return 46; }
        unsigned n = received(&cap, dma_frames[index]);
        if (n < 4 || dma_frames[index][0] != 0xff || dma_frames[index][1] != 0xd8 ||
            dma_frames[index][n-2] != 0xff || dma_frames[index][n-1] != 0xd9) return 47;
        if (held >= 0 && previous_hash != hash(dma_frames[held], slots[held].length)) return 48;
        if (dma_buffer_complete(&slots[index], n) || release_held() ||
            dma_buffer_advance(&slots[index], DMA_SENDING)) return 49;
        held = index;
        dma_job.completed++; dma_job.bytes += n; dma_job.frames++;
        if (n > dma_job.max_length) dma_job.max_length = n;
        if (run % 100 == 0) xil_printf("DMA CAMERA frame=%u bytes=%u\r\n", run, n);
    }
    // Leave the selected DDR buffer SENDING, no active DMA can overwrite it while host reads.
    if (reset_dma()) return 50;
    dma_job.address = (uint32_t)(UINTPTR)dma_frames[held];
    dma_job.length = slots[held].length;
    dma_job.checksum = hash(dma_frames[held], slots[held].length);
    dma_job.queued = stat(1); dma_job.dropped = stat(2); dma_job.overflows = stat(3);
    dma_job.peak = stat(4); dma_job.sent = stat(5);
    route(1, 1); usleep(1000);
    return 0;
}
static void fault(void *arg)
{
    Xil_DCacheDisable(); dma_job.status = 90U + (unsigned)(UINTPTR)arg;
    __asm__ volatile("dsb sy" ::: "memory"); dma_job.state = 3;
    xil_printf("DMA EXCEPTION status=%u\r\n", dma_job.status);
    for (;;) { }
}
int main(void)
{
    XUartPs uart;
    XUartPs_Config *cfg = XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
    Xil_DCacheDisable();
    if (!cfg || XUartPs_CfgInitialize(&uart, cfg, cfg->BaseAddress) || XUartPs_SetBaudRate(&uart, 115200)) return 1;
    usleep(1); // Native xiltimer lazily starts AND zeros the global counter; do this before timestamps/deadlines.
    Xil_Out32(CAM_GPIO + 4, 0); Xil_Out32(CAM_GPIO + 12, 0xffffffffU);
    Xil_Out32(DMA_GPIO + 4, 0); Xil_Out32(DMA_GPIO + 12, 0xffffffffU);
    route(0, 1);
    if (stat(0) != 0x4d303531U || init_dma(&capture, CAP_BASE) || init_dma(&crypto, CRYPTO_BASE)) {
        xil_printf("DMA INIT FAIL\r\n"); return 2;
    }
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_DATA_ABORT_INT, fault, (void *)4);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_PREFETCH_ABORT_INT, fault, (void *)3);
    if (reset_dma()) return 3;
    dma_job.magic = MAGIC;
    xil_printf("DMA READY mailbox=%08x capacity=%u IRQ=native cache=off\r\n",
        (unsigned)(UINTPTR)&dma_job, DMA_FRAME_CAPACITY);
    for (;;) if (dma_job.state == 1) {
        unsigned cmd = dma_job.command, count = dma_job.count, cache = dma_job.cache;
        unsigned sensor_cfg = dma_job.reserved;
        XTime start;
        int result = 0;
        // Only command inputs are retained. Idle mailbox is uncached for JTAG ownership.
        memset((void *)&dma_job.status, 0, sizeof dma_job - offsetof(struct dma_job, status));
        dma_job.reserved = sensor_cfg;
        cap.interrupts = tx.interrupts = out.interrupts = 0;
        if (cache) Xil_DCacheEnable();
        XTime_GetTime(&start);
        if (dma_job.magic != MAGIC || cache > 1 || cmd < 1 || cmd > 3 || !count || count > 10000)
            result = 80;
        else if (cmd == 3) result = release_held();
        else if (held >= 0) result = 81; // Host must explicitly release a saved image first.
        else if (cmd == 2 && ((sensor_cfg & ~0x01fffffeU) || !(sensor_cfg & 2U) ||
                 (sensor_cfg >> 9) < 1000U || (sensor_cfg >> 9) > 5000U)) result = 83;
        else if (cmd == 1) {
            result = reset_dma();
            route(0, 1);
            unsigned stalls = stat(8);
            for (unsigned i = 0; i < count && !result; i++) {
                result = transfer(i, i < (count + 1U) / 2U ? 0 : 2);
                if (i % 1000 == 0) xil_printf("DMA TEST iteration=%u cache=%u status=%u\r\n", i, cache, result);
            }
            if (!result) result = recovery_tests();
            dma_job.stalls = stat(8) - stalls;
            if (!result && count >= 24U && !dma_job.stalls) result = 82;
        } else result = camera_frames(count, sensor_cfg);
        if (result) {
            dump();
            if (reset_dma()) result = 89;
            else route(route_cfg & 3U, 1);
        }
        dma_job.elapsed_us = elapsed_us(start);
        dma_job.rx_irq = cap.interrupts + out.interrupts; dma_job.tx_irq = tx.interrupts;
        dma_job.status = (unsigned)result;
        Xil_DCacheDisable(); // Flush result and invalidate stale RX lines BEFORE publishing DONE.
        xil_printf("DMA RESULT cmd=%u cache=%u status=%u completed=%u bytes=%u us=%u rx_irq=%u tx_irq=%u\r\n",
            cmd, cache, dma_job.status, dma_job.completed, dma_job.bytes, dma_job.elapsed_us,
            dma_job.rx_irq, dma_job.tx_irq);
        __asm__ volatile("dsb sy" ::: "memory"); dma_job.state = result ? 3 : 2;
    }
}
