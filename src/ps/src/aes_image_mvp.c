/* JTAG-only, owned DDR mailbox. No GEM, camera, DMA, or second interrupt stack. */
#include "xparameters.h"
#include "xil_cache.h"
#include "xil_exception.h"
#include "xil_io.h"
#include "xil_printf.h"
#include "xil_testmem.h"
#include "xiltimer.h"
#include "xuartps.h"
#include "mvp_gcm.h"
#include <stddef.h>

#define AES_BASE 0x43c00000U
#define MVP_MAGIC 0x3150564dU
struct image_job {
    uint32_t magic, state, status, length;
    uint8_t key[16], nonce[12], aad[16], data[MVP_MAX_IMAGE], tag[16];
};
volatile struct image_job mvp_job __attribute__((aligned(64)));
_Static_assert(offsetof(struct image_job, state) == 4, "mailbox state offset");
_Static_assert(offsetof(struct image_job, data) == 60, "mailbox payload offset");
_Static_assert(sizeof(struct image_job) == MVP_MAX_IMAGE + 76, "mailbox ABI");

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static int aes_wait(uint32_t required)
{
    XTime start, now;
    XTime_GetTime(&start);
    do {
        uint32_t status = Xil_In32(AES_BASE + 4);
        if (!(status & 1U) && (status & required) == required) return 0;
        XTime_GetTime(&now);
    } while (now - start < COUNTS_PER_SECOND / 100U); // 10 ms, not an unbounded poll.
    return 1;
}

static int aes_block(void *context, const uint8_t in[16], uint8_t out[16])
{
    unsigned int i;
    (void)context;
    for (i = 0; i < 4; i++) Xil_Out32(AES_BASE + 0x20 + i * 4, get32(in + i * 4));
    Xil_Out32(AES_BASE, 2);
    if (aes_wait(6)) return 1;
    for (i = 0; i < 4; i++) {
        uint32_t value = Xil_In32(AES_BASE + 0x30 + i * 4);
        out[i * 4] = (uint8_t)(value >> 24); out[i * 4 + 1] = (uint8_t)(value >> 16);
        out[i * 4 + 2] = (uint8_t)(value >> 8); out[i * 4 + 3] = (uint8_t)value;
    }
    return 0;
}

static void fault(void *id)
{
    mvp_zero((void *)mvp_job.key, sizeof mvp_job.key);
    mvp_zero((void *)mvp_job.nonce, sizeof mvp_job.nonce);
    mvp_zero((void *)mvp_job.data, sizeof mvp_job.data);
    mvp_zero((void *)mvp_job.tag, sizeof mvp_job.tag);
    Xil_DCacheDisable(); // Flush zeroization before publishing an exception to JTAG.
    mvp_job.status = 3;
    __asm__ volatile("dsb sy" ::: "memory");
    mvp_job.state = 3;
    xil_printf("MVP EXCEPTION id=%u\r\n", (unsigned int)(UINTPTR)id);
    for (;;) { }
}

int main(void)
{
    XUartPs uart;
    XUartPs_Config *cfg = XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
    if (!cfg || XUartPs_CfgInitialize(&uart, cfg, cfg->BaseAddress) != XST_SUCCESS ||
        XUartPs_SetBaudRate(&uart, 115200) != XST_SUCCESS) return 1;
    Xil_DCacheDisable(); // JTAG owns DDR while idle; PS uses cache only during a job.
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_DATA_ABORT_INT, fault, (void *)4);
    Xil_ExceptionRegisterHandler(XIL_EXCEPTION_ID_PREFETCH_ABORT_INT, fault, (void *)3);
    xil_printf("MVP BOOT uart=115200 cache=off\r\n");
    if (Xil_TestMem32((uint32_t *)mvp_job.data, MVP_MAX_IMAGE / 4, 0xa5a55a5a,
                      XIL_TESTMEM_ALLMEMTESTS) != XST_SUCCESS) {
        xil_printf("MVP DDR FAIL\r\n"); return 2;
    }
    xil_printf("MVP DDR PASS; checking PL AES ID\r\n");
    if (Xil_In32(AES_BASE + 8) != 0x41455331U) { xil_printf("MVP AES ID FAIL\r\n"); return 3; }
    Xil_Out32(AES_BASE, 4);
    mvp_job.state = 0;
    __asm__ volatile("dsb sy" ::: "memory");
    mvp_job.magic = MVP_MAGIC;
    xil_printf("MVP READY mailbox=%08x max_image=%u PL=AES128 PS=GHASH\r\n",
               (unsigned int)(UINTPTR)&mvp_job, MVP_MAX_IMAGE);
    for (;;) {
        if (mvp_job.state == 1) {
            XTime start, end;
            unsigned int i;
            int error = 2;
            uint32_t length = mvp_job.length;
            Xil_DCacheEnable(); // Input is complete; JTAG now only polls the unchanged state.
            mvp_job.status = 0;
            XTime_GetTime(&start);
            if (mvp_job.magic == MVP_MAGIC && length <= MVP_MAX_IMAGE &&
                get32((const uint8_t *)mvp_job.aad) == 0x4d565031U &&
                get32((const uint8_t *)mvp_job.aad + 4) == 1 &&
                get32((const uint8_t *)mvp_job.aad + 8) == length &&
                get32((const uint8_t *)mvp_job.aad + 12) == 0) {
                for (i = 0; i < 4; i++)
                    Xil_Out32(AES_BASE + 0x10 + i * 4, get32((const uint8_t *)mvp_job.key + i * 4));
                Xil_Out32(AES_BASE, 1);
                error = aes_wait(2);
                if (!error) error = mvp_gcm_encrypt((uint8_t *)mvp_job.data, length,
                    (const uint8_t *)mvp_job.nonce, (const uint8_t *)mvp_job.aad, 16,
                    (uint8_t *)mvp_job.tag, aes_block, NULL);
            }
            Xil_Out32(AES_BASE, 4); // Clears wrapper and upstream round-key/state registers.
            mvp_zero((void *)mvp_job.key, sizeof mvp_job.key);
            mvp_zero((void *)mvp_job.nonce, sizeof mvp_job.nonce);
            if (error) {
                mvp_zero((void *)mvp_job.data, sizeof mvp_job.data);
                mvp_zero((void *)mvp_job.tag, sizeof mvp_job.tag);
            }
            XTime_GetTime(&end);
            mvp_job.status = (uint32_t)error;
            Xil_DCacheDisable(); // Flush ciphertext/tag and cleared secrets before DONE.
            xil_printf("MVP RESULT bytes=%u status=%u elapsed_us=%u\r\n", length,
                (unsigned int)error, (unsigned int)((end - start) / (COUNTS_PER_SECOND / 1000000U)));
            __asm__ volatile("dsb sy" ::: "memory");
            mvp_job.state = error ? 3 : 2; // Publish only after ciphertext/tag and zeroization.
        }
    }
}
