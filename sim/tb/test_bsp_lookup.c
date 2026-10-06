/* Run on PC with the real generated BSP tables and AMD lookup sources.
 * No peripheral initialization or MMIO is performed. */
#include <assert.h>
#include <stdio.h>
#include "bsp_compat.h"
#include "xusbps.h"

int main(void)
{
    XAxiDma_Config *capture = eye_dma_config(0x40400000U);
    XAxiDma_Config *crypto = eye_dma_config(0x40410000U);
    XUartPs_Config *uart = eye_uart_config();
    XUsbPs_Config *usb = XUsbPs_LookupConfig(XPAR_XUSBPS_0_DEVICE_ID);
    assert(capture && crypto && uart && usb);
    assert(capture->BaseAddr == 0x40400000U && capture->HasS2Mm && !capture->HasMm2S);
    assert(crypto->BaseAddr == 0x40410000U && crypto->HasS2Mm && crypto->HasMm2S);
    assert(uart->BaseAddress == STDOUT_BASEADDRESS);
    assert(usb->BaseAddress == XPAR_XUSBPS_0_BASEADDR);
    assert(!eye_dma_config(0x40420000U));
    puts("BSP_LOOKUP_PASS real_generated_tables dma_capture dma_crypto uart usb");
    return 0;
}
