/* Exercises the real probe cleanup path with the pinned XUsbPs SDK types/macros. */
#define G6_USB 1
#define USB_LIBRARY 1
#include "../../prj/usb_probe_auto_recovery.c"

#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
#endif

volatile struct g6_secure_cleanup_diag g6_secure_cleanup_diag;
static volatile u32 *registers;
static XUsbPs_dTD *descriptors;
static XUsbPs_dQH *queue_head;
static void *low_dma_fixture;
static uint8_t test_tx[G6_SECURE_TX_CAPACITY] __attribute__((aligned(64)));
static unsigned rebuild_calls;
static unsigned endpoint_faulted;
static int simulate_send_status;
static int simulate_completion;
static int simulate_disconnect_after_completion;
static const u8 *simulate_callback_data;
static u32 simulate_completion_token;
static u32 simulate_requested_bytes;

int XUsbPs_EpPrime(XUsbPs *instance, u8 ep, u8 direction)
{
    (void)instance; (void)ep; (void)direction; return XST_SUCCESS;
}

int XUsbPs_EpBufferSend(XUsbPs *instance, u8 ep, const u8 *buffer, u32 length)
{
    if (simulate_send_status != XST_SUCCESS) return simulate_send_status;
    if (simulate_completion && ep == 1U) {
        XUsbPs_EpIn *in = &instance->DeviceConfig.Ep[ep].In;
        XUsbPs_dTD *td = in->dTDHead;
        XUsbPs_WritedTD(td, XUSBPS_dTDUSERDATA, (u32)(UINTPTR)buffer);
        XUsbPs_WritedTD(td, XUSBPS_dTDTOKEN, simulate_completion_token);
        in->RequestedBytes = simulate_requested_bytes == UINT32_MAX
            ? length : simulate_requested_bytes;
        ep1_in(instance, ep, XUSBPS_EP_EVENT_DATA_TX,
               (void *)(simulate_callback_data ? simulate_callback_data : buffer));
        if (simulate_disconnect_after_completion) {
            dtr = 0;
            ++connection_epoch;
        }
    }
    return XST_SUCCESS;
}

int XUsbPs_EpBufferReceive(XUsbPs *instance, u8 ep, u8 **buffer, u32 *length,
                           u32 *handle)
{
    (void)instance; (void)ep; (void)buffer; (void)length; (void)handle;
    return XST_FAILURE;
}

void XUsbPs_EpBufferRelease(u32 handle) { (void)handle; }

int XUsbPs_EpGetSetupData(XUsbPs *instance, int ep, XUsbPs_SetupData *setup)
{
    (void)instance; (void)ep; (void)setup; return XST_FAILURE;
}

int XUsbPs_Ch9HandleSetupPacket(XUsbPs *instance, XUsbPs_SetupData *setup)
{
    (void)instance; (void)setup; return XST_FAILURE;
}

void XTime_GetTime(XTime *ticks) { *ticks = 0U; }

void Xil_DCacheFlushRange(INTPTR address, u32 length)
{
    (void)address; (void)length;
}

void Xil_DCacheInvalidateRange(INTPTR address, u32 length)
{
    (void)address; (void)length;
}

int XUsbPs_BoundedEndpointIsFaulted(XUsbPs *instance, u8 ep)
{
    (void)instance; (void)ep; return (int)endpoint_faulted;
}

int XUsbPs_ReconfigureEp(XUsbPs *instance, XUsbPs_DeviceConfig *config,
                         int ep, unsigned short direction, int changed)
{
    (void)instance; (void)changed;
    ++rebuild_calls;
    if (direction == XUSBPS_EP_DIRECTION_IN) {
        config->Ep[ep].In.dTDHead = config->Ep[ep].In.dTDs;
        config->Ep[ep].In.dTDTail = config->Ep[ep].In.dTDs;
    }
    return XST_SUCCESS;
}

void XUsbPs_BoundedClearEndpointFault(XUsbPs *instance, u8 ep)
{
    (void)instance; (void)ep; endpoint_faulted = 0U;
}

static int bytes_are(const void *memory, size_t length, uint8_t value)
{
    const uint8_t *bytes = memory;
    for (size_t i = 0; i < length; ++i)
        if (bytes[i] != value) return 0;
    return 1;
}

static void reset_fixture(void)
{
    memset((void *)&usb, 0, sizeof usb);
    memset((void *)&g6_secure_cleanup_diag, 0, sizeof g6_secure_cleanup_diag);
    if (!low_dma_fixture) {
#ifdef _WIN32
        low_dma_fixture = VirtualAlloc((void *)(uintptr_t)0x10000000U,
            0x1000U, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
#endif
        if (!low_dma_fixture || (uintptr_t)low_dma_fixture > UINT32_MAX - 0x1000U)
            abort();
        descriptors = (XUsbPs_dTD *)low_dma_fixture;
        queue_head = (XUsbPs_dQH *)((uint8_t *)low_dma_fixture + 0x100U);
        registers = (volatile u32 *)((uint8_t *)low_dma_fixture + 0x200U);
    }
    memset((void *)registers, 0, 0x200U);
    memset(descriptors, 0, 4U * sizeof(*descriptors));
    memset(queue_head, 0x5a, sizeof(*queue_head));
    *(u32 *)((uint8_t *)queue_head + XUSBPS_dQHdTDTOKEN) = 0U;
    memset(test_tx, 0xa5, sizeof test_tx);
    usb.Config.BaseAddress = (u32)(uintptr_t)registers;
    usb.DeviceConfig.Ep[1].In.dQH = queue_head;
    usb.DeviceConfig.Ep[1].In.dTDs = descriptors;
    usb.DeviceConfig.Ep[1].In.dTDHead = &descriptors[0];
    usb.DeviceConfig.Ep[1].In.dTDTail = &descriptors[0];
    usb.DeviceConfig.EpCfg[1].In.NumBufs = 4U;
    for (unsigned i = 0; i < 4U; ++i)
        XUsbPs_dTDSetNLP(&descriptors[i],
            (u32)(uintptr_t)&descriptors[(i + 1U) % 4U]);
    configured = dtr = tx_ready = 1;
    connection_epoch = 0U;
    tx_pending = 0;
    tx_pending_buffer = NULL;
    tx_pending_td = NULL;
    tx_pending_size = tx_pending_epoch = 0U;
    tx_completion_count = 0U;
    tx_completion_status = USB_TX_RESULT_NOT_COMPLETED;
    tx_completion_token = USB_TX_RESULT_NOT_COMPLETED;
    tx_completion_residual = USB_TX_RESULT_NOT_COMPLETED;
    tx_completion_requested = USB_TX_RESULT_NOT_COMPLETED;
    tx_completion_expected = USB_TX_RESULT_NOT_COMPLETED;
    tx_completion_match_flags = 0U;
    simulate_send_status = XST_SUCCESS;
    simulate_completion = 0;
    simulate_disconnect_after_completion = 0;
    simulate_callback_data = NULL;
    simulate_completion_token = 0U;
    simulate_requested_bytes = UINT32_MAX;
    registers[XUSBPS_EPCR1_OFFSET / 4U] = XUSBPS_EPCR_TXE_MASK;
    rebuild_calls = endpoint_faulted = 0U;
}

static int test_idle_wipe_preserves_pipe(void)
{
    XUsbPs_dTD td_before[4];
    XUsbPs_dQH qh_before;
    XUsbPs_dTD *head, *tail;
    reset_fixture();
    memcpy(td_before, descriptors, sizeof td_before);
    memcpy(&qh_before, queue_head, sizeof qh_before);
    head = usb.DeviceConfig.Ep[1].In.dTDHead;
    tail = usb.DeviceConfig.Ep[1].In.dTDTail;
    int status = usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx);
    if (status != 0) {
        fprintf(stderr, "idle status=%d path=%u stage=%u result=%u eprdy=%u polls=%u flush=%u prime=%u qstatus=%u zero=%u\n",
            status, (unsigned)g6_secure_cleanup_diag.usb_cleanup_path,
            (unsigned)g6_secure_cleanup_diag.stage,
            (unsigned)g6_secure_cleanup_diag.result,
            (unsigned)g6_secure_cleanup_diag.usb_ownership_eprdystatus,
            (unsigned)g6_secure_cleanup_diag.usb_ownership_eprdy_polls,
            (unsigned)g6_secure_cleanup_diag.usb_flush_status,
            (unsigned)g6_secure_cleanup_diag.usb_prime_status,
            (unsigned)g6_secure_cleanup_diag.usb_quiesce_status,
            (unsigned)g6_secure_cleanup_diag.tx_zero_or);
        return 1;
    }
    if (!bytes_are(test_tx, sizeof test_tx, 0U) ||
        g6_secure_cleanup_diag.tx_zero_or != 0U ||
        g6_secure_cleanup_diag.usb_cleanup_path != G6_USB_CLEANUP_PATH_IDLE_WIPE ||
        g6_secure_cleanup_diag.usb_quiesce_status != 0U ||
        g6_secure_cleanup_diag.usb_flush_status != 0U ||
        g6_secure_cleanup_diag.usb_prime_status != 0U ||
        g6_secure_cleanup_diag.usb_completion_status != 0U ||
        g6_secure_cleanup_diag.usb_poll_limit != G6_USB_TX_QUIESCE_POLL_LIMIT ||
        g6_secure_cleanup_diag.usb_flush_polls != 0U ||
        g6_secure_cleanup_diag.usb_prime_polls != 0U ||
        g6_secure_cleanup_diag.usb_rebuild_status != 0U ||
        g6_secure_cleanup_diag.usb_ownership_eprdystatus != 0U ||
        g6_secure_cleanup_diag.usb_ownership_eprdy_polls != 1U ||
        rebuild_calls ||
        usb.DeviceConfig.Ep[1].In.dTDHead != head ||
        usb.DeviceConfig.Ep[1].In.dTDTail != tail ||
        memcmp(td_before, descriptors, sizeof td_before) ||
        memcmp(&qh_before, queue_head, sizeof qh_before) ||
        registers[XUSBPS_EPCR1_OFFSET / 4U] != XUSBPS_EPCR_TXE_MASK ||
        registers[XUSBPS_EPCOMPL_OFFSET / 4U] != 0U)
        return 2;
    return 0;
}

static int test_active_or_nonidle_uses_quiesce_path(void)
{
    reset_fixture();
    XUsbPs_dTDSetActive(&descriptors[0]);
    if (usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx) == 0) return 1;
    if (g6_secure_cleanup_diag.usb_cleanup_path != G6_USB_CLEANUP_PATH_QUIESCE_REBUILD ||
        rebuild_calls != 0U ||
        g6_secure_cleanup_diag.usb_quiesce_status == 0U ||
        !bytes_are(test_tx, sizeof test_tx, 0xa5U)) return 2;

    reset_fixture();
    usb.DeviceConfig.Ep[1].In.dTDHead = &descriptors[1];
    registers[XUSBPS_EPRDY_OFFSET / 4U] = 1U << 17U;
    if (usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx) == 0) return 3;
    if (g6_secure_cleanup_diag.usb_cleanup_path != G6_USB_CLEANUP_PATH_QUIESCE_REBUILD ||
        rebuild_calls != 0U || g6_secure_cleanup_diag.usb_quiesce_status == 0U ||
        !bytes_are(test_tx, sizeof test_tx, 0xa5U))
        return 4;
    return 0;
}

static int test_corrupt_ring_fails_closed_before_wipe(void)
{
    reset_fixture();
    usb.DeviceConfig.Ep[1].In.dTDHead = (XUsbPs_dTD *)(uintptr_t)0x1234U;
    if (usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx) == 0) return 1;
    if (g6_secure_cleanup_diag.usb_cleanup_path != G6_USB_CLEANUP_PATH_FAILED ||
        !bytes_are(test_tx, sizeof test_tx, 0xa5U) || rebuild_calls) return 2;

    reset_fixture();
    usb.DeviceConfig.EpCfg[1].In.NumBufs = 3U;
    if (usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx) == 0) return 3;
    if (!bytes_are(test_tx, sizeof test_tx, 0xa5U) || rebuild_calls)
        return 4;

    reset_fixture();
    configured = 0;
    usb.DeviceConfig.Ep[1].In.dTDTail = (XUsbPs_dTD *)(uintptr_t)0x1234U;
    if (usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx) == 0) return 5;
    if (g6_secure_cleanup_diag.usb_cleanup_path != G6_USB_CLEANUP_PATH_FAILED ||
        !bytes_are(test_tx, sizeof test_tx, 0xa5U) || rebuild_calls)
        return 6;

    reset_fixture();
    XUsbPs_WritedTD(&descriptors[0], XUSBPS_dTDTOKEN,
                    XUSBPS_dTDTOKEN_HALT_MASK);
    if (usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx) == 0) return 7;
    if (g6_secure_cleanup_diag.usb_cleanup_path !=
            G6_USB_CLEANUP_PATH_QUIESCE_REBUILD ||
        !bytes_are(test_tx, sizeof test_tx, 0xa5U) || rebuild_calls)
        return 8;
    return 0;
}

static int expect_fallback_without_wipe(void)
{
    if (usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx) == 0) return 1;
    if (g6_secure_cleanup_diag.usb_cleanup_path !=
            G6_USB_CLEANUP_PATH_QUIESCE_REBUILD ||
        g6_secure_cleanup_diag.usb_quiesce_status == 0U ||
        rebuild_calls || !bytes_are(test_tx, sizeof test_tx, 0xa5U))
        return 2;
    return 0;
}

static int test_idle_ownership_rejections_fall_back(void)
{
    reset_fixture();
    registers[XUSBPS_EPCOMPL_OFFSET / 4U] = 1U << 17U;
    if (expect_fallback_without_wipe()) return 1;

    const u32 bad_qh_tokens[] = {
        XUSBPS_dTDTOKEN_ACTIVE_MASK,
        XUSBPS_dTDTOKEN_XERR_MASK,
        XUSBPS_dTDTOKEN_BUFERR_MASK,
        XUSBPS_dTDTOKEN_HALT_MASK,
    };
    for (unsigned i = 0; i < sizeof bad_qh_tokens / sizeof bad_qh_tokens[0]; ++i) {
        reset_fixture();
        XUsbPs_WritedQH(queue_head, XUSBPS_dQHdTDTOKEN, bad_qh_tokens[i]);
        if (expect_fallback_without_wipe()) return (int)(10U + i);
    }

    reset_fixture();
    endpoint_faulted = 1U;
    if (expect_fallback_without_wipe()) return 20;
    return 0;
}

static int test_tx_completion_requires_matching_successful_descriptor(void)
{
    reset_fixture();
    simulate_completion = 1;
    if (usb_cdc_send(test_tx, 64U) != 0 || !tx_ready || tx_pending ||
        tx_completion_status != 0U || tx_completion_count != 1U ||
        tx_completion_residual != 0U || tx_completion_requested != 64U ||
        tx_completion_expected != 64U || tx_completion_match_flags != 31U)
        return 1;

    const u32 failed_tokens[] = {
        XUSBPS_dTDTOKEN_HALT_MASK,
        XUSBPS_dTDTOKEN_XERR_MASK,
        XUSBPS_dTDTOKEN_BUFERR_MASK,
        3U << 16U,
    };
    for (unsigned i = 0; i < sizeof failed_tokens / sizeof failed_tokens[0]; ++i) {
        reset_fixture();
        simulate_completion = 1;
        simulate_completion_token = failed_tokens[i];
        if (usb_cdc_send(test_tx, 64U) != USB_TX_RESULT_TRANSFER_ERROR ||
            !tx_ready || tx_pending || tx_completion_status != USB_TX_RESULT_TRANSFER_ERROR)
            return (int)(10U + i);
    }

    /* An active dTD or a mismatched callback pointer leaves ownership unknown.
     * The send returns as disconnected, but cleanup must prove quiescence before release. */
    reset_fixture();
    simulate_completion = 1;
    simulate_completion_token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
    simulate_disconnect_after_completion = 1;
    if (usb_cdc_send(test_tx, 64U) != 1 || tx_ready || !tx_pending ||
        tx_completion_status != USB_TX_RESULT_OWNERSHIP_UNCERTAIN)
        return 20;
    int cleanup_status = usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx);
    if ((!cleanup_status && (!tx_ready || tx_pending)) ||
        (cleanup_status && (tx_ready || !tx_pending))) return 21;

    reset_fixture();
    simulate_completion = 1;
    simulate_callback_data = test_tx + 1;
    simulate_disconnect_after_completion = 1;
    if (usb_cdc_send(test_tx, 64U) != 1 || tx_ready || !tx_pending ||
        tx_completion_status != USB_TX_RESULT_OWNERSHIP_UNCERTAIN ||
        tx_completion_match_flags != 30U)
        return 22;
    cleanup_status = usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx);
    if ((!cleanup_status && (!tx_ready || tx_pending)) ||
        (cleanup_status && (tx_ready || !tx_pending))) return 23;

    /* Queue failure also keeps the buffer locked until cleanup proves that the
     * SDK did not leave a descriptor owning it. */
    reset_fixture();
    simulate_send_status = XST_FAILURE;
    if (usb_cdc_send(test_tx, 64U) != 3 || tx_ready || !tx_pending ||
        tx_completion_status != 3U)
        return 24;
    cleanup_status = usb_cdc_secure_cleanup_tx(test_tx, sizeof test_tx);
    if ((!cleanup_status && (!tx_ready || tx_pending)) ||
        (cleanup_status && (tx_ready || !tx_pending))) return 25;
    return 0;
}

int main(void)
{
    int idle = test_idle_wipe_preserves_pipe();
    int fallback = test_active_or_nonidle_uses_quiesce_path();
    int corrupt = test_corrupt_ring_fails_closed_before_wipe();
    int ownership = test_idle_ownership_rejections_fall_back();
    int tx_completion = test_tx_completion_requires_matching_successful_descriptor();
    if (idle || fallback || corrupt || ownership || tx_completion) {
        fprintf(stderr, "g6_usb_idle_fastpath_failed=%d,%d,%d,%d tx_completion=%d\n",
                idle, fallback, corrupt, ownership, tx_completion);
        return 1;
    }
    puts("actual_probe_idle_wipe_preserves_pipe=PASS active_fallback=PASS corrupt_fail_closed=PASS completion_qh_fault_fallback=PASS tx_completion_ownership=PASS");
    return 0;
}
