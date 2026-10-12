/* Driver lookup differs between classic HSI and system device-tree BSPs. */
#ifndef EYE_BSP_COMPAT_H
#define EYE_BSP_COMPAT_H
#include "xparameters.h"
#include "xaxidma.h"
#include "xuartps.h"

static inline XAxiDma_Config *eye_dma_config(UINTPTR base)
{
#ifdef SDT
    return XAxiDma_LookupConfig(base);
#else
    return XAxiDma_LookupConfigBaseAddr(base);
#endif
}

static inline XUartPs_Config *eye_uart_config(void)
{
#ifdef SDT
    return XUartPs_LookupConfig(XPAR_XUARTPS_0_BASEADDR);
#else
    return XUartPs_LookupConfig(XPAR_XUARTPS_0_DEVICE_ID);
#endif
}
#endif
