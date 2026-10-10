/* Runtime integration mock for the generated USB SETUP interrupt overlay and
 * the generated CDC probe callbacks.  The runner supplies mock_sdk.h and the
 * generated sources on the include path; hardware and cache primitives are
 * deterministic stubs below. */
#include "mock_sdk.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#include "xusbps_intr.c"
#include "xusbps_ch9.c"
#include "usb_probe_bounded_generated.c"

#define REG_WORDS 256U
#define OUT0_BIT  (1U << 0)
#define IN0_BIT   (1U << 16)
#define OUT1_BIT  (1U << 1)
#define IN1_BIT   (1U << 17)

static u32 regs[REG_WORDS];
static XUsbPs_SetupData wire_setup;
static XUsbPs_SetupData injected_setup;
static int inject_setup_during_prepare;
static int inject_after_first_flush;
static int fail_out_flush;
static int fail_in_flush;
static int prime_stuck;
static int fail_out_prime;
static int fail_send;
static int send_completes_immediately;
static unsigned setup_reads;
static unsigned prime_out_count;
static unsigned prime_in_count;
static unsigned flush_out_count;
static unsigned flush_in_count;
static unsigned disable_count;
static unsigned enable_count;
static unsigned stall_count;
static unsigned unstall_count;
static unsigned receive_count;
static unsigned release_count;
static unsigned send_count;
static unsigned ep1_rx_count;
static unsigned ep1_tx_count;
static unsigned cache_invalidate_count;
static unsigned cache_flush_count;
static unsigned epcompl_ack_before_send;
static unsigned epcompl_ack_after_send;
static int saw_exact_tail_invalidate;
static int stale_line_coding_owned;
static u8 stale_line_coding_snapshot[8];
static const u8 *last_send_buffer;
static u32 last_send_length;
static u8 rx_buffer[64];
static u32 rx_length;
static int rx_available;
static int out_disabled, in_disabled;
static u32 fault_mask;

static void count_ep1_rx(void *ref, u8 ep, u8 event, void *data);
static void count_ep1_tx(void *ref, u8 ep, u8 event, void *data);

/* QH occupies a 64-byte SDK slot. Keep setup words at offsets 0x28/0x2c in
 * the same 32-byte cache line as the sentinel at 0x20. */
typedef struct __attribute__((aligned(64))) {
	XUsbPs_dQH qh;
} qh_slot_t;
static qh_slot_t qh_slots[6];
static XUsbPs_dTD out0_td[2], in0_td[4], out1_td[2], in1_td[2];
static u8 out0_data[2][64], out1_data[2][64];

static void set_setup(u8 request, u8 request_type, u16 value, u16 length)
{
	memset(&wire_setup, 0, sizeof(wire_setup));
	wire_setup.bRequest = request;
	wire_setup.bmRequestType = request_type;
	wire_setup.wValue = value;
	wire_setup.wLength = length;
	qh_slots[0].qh.words[10] = (u32)request_type | ((u32)request << 8) |
		((u32)value << 16);
	qh_slots[0].qh.words[11] = (u32)length << 16;
}

static void ring_init(XUsbPs_dTD *ring, unsigned count, int active)
{
	unsigned i;
	for (i = 0; i < count; ++i) {
		memset(&ring[i], 0, sizeof(ring[i]));
		ring[i].next = &ring[(i + 1U) % count];
		ring[i].nlp = (u32)(uintptr_t)&ring[(i + 1U) % count];
		ring[i].active = active ? 1U : 0U;
		ring[i].token = active ? XUSBPS_dTDTOKEN_ACTIVE_MASK : 0U;
	}
}

static void fixture_reset(void)
{
	unsigned i;
	memset(&usb, 0, sizeof(usb));
	memset(regs, 0, sizeof(regs));
	memset(qh_slots, 0, sizeof(qh_slots));
	memset(&wire_setup, 0, sizeof(wire_setup));
	memset(&injected_setup, 0, sizeof(injected_setup));
	memset(rx_buffer, 0, sizeof(rx_buffer));
	memset(line_coding, 0, sizeof(line_coding));
	line_coding[0] = 0x00U; line_coding[1] = 0xc2U;
	line_coding[2] = 0x01U; line_coding[6] = 8U;
	configured = dtr = mode = line_pending = 0;
	tx_ready = 1;
	connection_epoch = test_epoch = test_epoch_bytes = 0U;
	usb_recovery_failures = 0U;
	for (i = 0; i < sizeof(qh_slots) / sizeof(qh_slots[0]); ++i) {
		qh_slots[i].qh.words[8] = 0xfeed0020U + i;
		qh_slots[i].qh.words[10] = 0xfeed0028U + i;
		qh_slots[i].qh.words[11] = 0xfeed002cU + i;
	}
	usb.Config.BaseAddress = 0x1000U;
	usb.DeviceConfig.NumEndpoints = 3U;
	usb.DeviceConfig.EpCfg[0].Out.NumBufs = 2U;
	usb.DeviceConfig.EpCfg[0].Out.BufSize = 64U;
	usb.DeviceConfig.EpCfg[0].Out.MaxPacketSize = 64U;
	usb.DeviceConfig.EpCfg[0].Out.Type = XUSBPS_EP_TYPE_CONTROL;
	usb.DeviceConfig.EpCfg[0].In.NumBufs = 4U;
	usb.DeviceConfig.EpCfg[0].In.MaxPacketSize = 64U;
	usb.DeviceConfig.EpCfg[0].In.Type = XUSBPS_EP_TYPE_CONTROL;
	usb.DeviceConfig.EpCfg[1].Out.NumBufs = 2U;
	usb.DeviceConfig.EpCfg[1].Out.BufSize = 64U;
	usb.DeviceConfig.EpCfg[1].Out.Type = XUSBPS_EP_TYPE_BULK;
	usb.DeviceConfig.EpCfg[1].In.NumBufs = 2U;
	usb.DeviceConfig.EpCfg[1].In.Type = XUSBPS_EP_TYPE_BULK;
	usb.DeviceConfig.Ep[0].Out.dTDs = out0_td;
	usb.DeviceConfig.Ep[0].Out.dTDCurr = out0_td;
	usb.DeviceConfig.Ep[0].Out.dQH = &qh_slots[0].qh;
	usb.DeviceConfig.Ep[0].Out.dTDBufs = &out0_data[0][0];
	usb.DeviceConfig.Ep[0].Out.BufferPtr = out0_data[0];
	usb.DeviceConfig.Ep[0].In.dTDs = in0_td;
	usb.DeviceConfig.Ep[0].In.dTDHead = in0_td;
	usb.DeviceConfig.Ep[0].In.dTDTail = in0_td;
	usb.DeviceConfig.Ep[0].In.dQH = &qh_slots[1].qh;
	usb.DeviceConfig.Ep[1].Out.dTDs = out1_td;
	usb.DeviceConfig.Ep[1].Out.dTDCurr = out1_td;
	usb.DeviceConfig.Ep[1].Out.dQH = &qh_slots[2].qh;
	usb.DeviceConfig.Ep[1].Out.dTDBufs = &out1_data[0][0];
	usb.DeviceConfig.Ep[1].Out.BufferPtr = out1_data[0];
	usb.DeviceConfig.Ep[1].In.dTDs = in1_td;
	usb.DeviceConfig.Ep[1].In.dTDHead = in1_td;
	usb.DeviceConfig.Ep[1].In.dTDTail = in1_td;
	usb.DeviceConfig.Ep[1].In.dQH = &qh_slots[3].qh;
	usb.DeviceConfig.Ep[0].Out.HandlerFunc = ep0;
	usb.DeviceConfig.Ep[0].Out.HandlerRef = &usb;
	usb.DeviceConfig.Ep[1].Out.HandlerFunc = count_ep1_rx;
	usb.DeviceConfig.Ep[1].Out.HandlerRef = &usb;
	usb.DeviceConfig.Ep[1].In.HandlerFunc = count_ep1_tx;
	usb.DeviceConfig.Ep[1].In.HandlerRef = &usb;
	ring_init(out0_td, 2U, 1);
	ring_init(in0_td, 4U, 0);
	ring_init(out1_td, 2U, 0);
	ring_init(in1_td, 2U, 0);
	out0_td[0].bptr[0] = (u32)(uintptr_t)out0_data[0];
	out0_td[1].bptr[0] = (u32)(uintptr_t)out0_data[1];
	out1_td[0].bptr[0] = (u32)(uintptr_t)out1_data[0];
	out1_td[1].bptr[0] = (u32)(uintptr_t)out1_data[1];
	usb.DeviceConfig.Ep[0].In.dTDHead = in0_td;
	usb.DeviceConfig.Ep[0].In.dTDTail = in0_td;
	usb.DeviceConfig.Ep[1].In.dTDHead = in1_td;
	usb.DeviceConfig.Ep[1].In.dTDTail = in1_td;

	inject_setup_during_prepare = 0;
	inject_after_first_flush = 0;
	fail_out_flush = fail_in_flush = fail_out_prime = fail_send = prime_stuck = 0;
	send_completes_immediately = 1;
	setup_reads = prime_out_count = prime_in_count = 0U;
	flush_out_count = flush_in_count = disable_count = enable_count = 0U;
	stall_count = unstall_count = receive_count = release_count = send_count = 0U;
	ep1_rx_count = ep1_tx_count = 0U;
	cache_invalidate_count = cache_flush_count = 0U;
	epcompl_ack_before_send = epcompl_ack_after_send = 0U;
	saw_exact_tail_invalidate = 0;
	stale_line_coding_owned = 0;
	last_send_buffer = NULL;
	last_send_length = 0U;
	rx_length = 0U;
	rx_available = 0;
	out_disabled = in_disabled = 0;
	fault_mask = 0U;
	XUsbPs_Ch9OwnershipDiagnostics = (XUsbPs_Ch9OwnershipDiag){0};
}

static void count_ep1_rx(void *ref, u8 ep, u8 event, void *data)
{
	(void)ref; (void)data;
	assert(ep == 1U && event == XUSBPS_EP_EVENT_DATA_RX);
	++ep1_rx_count;
}

static void count_ep1_tx(void *ref, u8 ep, u8 event, void *data)
{
	(void)ref; (void)data;
	assert(ep == 1U && event == XUSBPS_EP_EVENT_DATA_TX);
	++ep1_tx_count;
}

u32 XUsbPs_ReadReg(UINTPTR base, u32 offset)
{
	u32 index = offset / 4U;
	(void)base;
	assert(index < REG_WORDS);
	if (offset == XUSBPS_EPFLUSH_OFFSET) {
		u32 value = regs[index];
		if (!fail_out_flush && !fail_in_flush)
			regs[index] = 0U;
		return value;
	}
	if (offset == XUSBPS_EPPRIME_OFFSET && !fail_out_flush && !fail_in_flush &&
	    !prime_stuck)
		regs[index] = 0U;
	return regs[index];
}

void XUsbPs_WriteReg(UINTPTR base, u32 offset, u32 value)
{
	u32 index = offset / 4U;
	(void)base;
	assert(index < REG_WORDS);
	if (offset == XUSBPS_EPCOMPL_OFFSET || offset == XUSBPS_ISR_OFFSET ||
	    offset == XUSBPS_EPSTAT_OFFSET) {
		if (offset == XUSBPS_EPCOMPL_OFFSET) {
			if (send_count == 0U) ++epcompl_ack_before_send;
			else ++epcompl_ack_after_send;
		}
		regs[index] &= ~value; /* write-one-to-clear */
	} else if (offset == XUSBPS_EPFLUSH_OFFSET) {
		regs[index] = value;
	} else {
		regs[index] = value;
	}
}

int XUsbPs_EpGetSetupData(XUsbPs *instance, int ep, XUsbPs_SetupData *out)
{
	assert(instance == &usb && ep == 0U && out != NULL);
	++setup_reads;
	{
		u32 setup0 = qh_slots[0].qh.words[10];
		u32 setup1 = qh_slots[0].qh.words[11];
		memset(out, 0, sizeof(*out));
		out->bmRequestType = (u8)(setup0 & 0xffU);
		out->bRequest = (u8)((setup0 >> 8) & 0xffU);
		out->wValue = (u16)(setup0 >> 16);
		out->wIndex = (u16)(setup1 & 0xffffU);
		out->wLength = (u16)(setup1 >> 16);
	}
	regs[XUSBPS_EPSTAT_OFFSET / 4U] = 0U;
	return XST_SUCCESS;
}

void Xil_DCacheInvalidateRange(UINTPTR address, u32 length)
{
	++cache_invalidate_count;
	if ((UINTPTR)address == (UINTPTR)&qh_slots[0].qh + 32U && length == 32U)
		saw_exact_tail_invalidate = 1;
}

void Xil_DCacheFlushRange(UINTPTR address, u32 length)
{
	(void)address; (void)length;
	++cache_flush_count;
}

void XUsbPs_dTDInvalidateCache(XUsbPs_dTD *td) { (void)td; }
void XUsbPs_dTDFlushCache(XUsbPs_dTD *td) { (void)td; }
void XUsbPs_dQHInvalidateCache(XUsbPs_dQH *qh)
{
	Xil_DCacheInvalidateRange((UINTPTR)qh, 64U);
}
void XUsbPs_dQHFlushCache(XUsbPs_dQH *qh)
{
	Xil_DCacheFlushRange((UINTPTR)qh, 64U);
}

int XUsbPs_BoundedEndpointIsFaulted(XUsbPs *instance, u8 ep)
{
	(void)instance;
	return (fault_mask & (1U << ep)) != 0U;
}

void XUsbPs_BoundedMarkEndpointFaulted(XUsbPs *instance, u8 ep)
{
	(void)instance;
	fault_mask |= 1U << ep;
}

void XUsbPs_BoundedClearEndpointFault(XUsbPs *instance, u8 ep)
{
	(void)instance;
	fault_mask &= ~(1U << ep);
}

void XUsbPs_BoundedClearEndpointFaults(XUsbPs *instance)
{
	(void)instance;
	fault_mask = 0U;
}

void XUsbPs_EpFlush(XUsbPs *instance, u8 ep, u8 direction)
{
	assert(instance == &usb && ep == 0U);
	if (direction & XUSBPS_EP_DIRECTION_OUT) {
		++flush_out_count;
		regs[XUSBPS_EPFLUSH_OFFSET / 4U] |= OUT0_BIT;
		if (!fail_out_flush) regs[XUSBPS_EPPRIME_OFFSET / 4U] &= ~OUT0_BIT;
		if (inject_setup_during_prepare && inject_after_first_flush &&
		    flush_out_count == 1U) {
			wire_setup = injected_setup;
			qh_slots[0].qh.words[10] =
				(u32)injected_setup.bmRequestType |
				((u32)injected_setup.bRequest << 8) |
				((u32)injected_setup.wValue << 16);
			qh_slots[0].qh.words[11] =
				(u32)injected_setup.wIndex |
				((u32)injected_setup.wLength << 16);
		}
	}
	if (direction & XUSBPS_EP_DIRECTION_IN) {
		++flush_in_count;
		regs[XUSBPS_EPFLUSH_OFFSET / 4U] |= IN0_BIT;
		if (!fail_in_flush) regs[XUSBPS_EPPRIME_OFFSET / 4U] &= ~IN0_BIT;
		if (stale_line_coding_owned)
			assert(memcmp(line_coding, stale_line_coding_snapshot,
				      sizeof(stale_line_coding_snapshot)) == 0);
	}
}

void XUsbPs_EpDisable(XUsbPs *instance, u8 ep, u8 direction)
{
	assert(instance == &usb && ep <= 2U);
	++disable_count;
	if (ep != 0U) {
		u32 mask = ((direction & XUSBPS_EP_DIRECTION_OUT) ? XUSBPS_EPCR_RXE_MASK : 0U) |
			   ((direction & XUSBPS_EP_DIRECTION_IN) ? XUSBPS_EPCR_TXE_MASK : 0U);
		regs[XUSBPS_EPCRn_OFFSET(ep) / 4U] &= ~mask;
		return;
	}
	if (direction & XUSBPS_EP_DIRECTION_OUT) out_disabled = 1;
	if (direction & XUSBPS_EP_DIRECTION_IN) in_disabled = 1;
}

void XUsbPs_EpEnable(XUsbPs *instance, u8 ep, u8 direction)
{
	assert(instance == &usb && ep <= 2U);
	++enable_count;
	if (ep != 0U) {
		u32 mask = ((direction & XUSBPS_EP_DIRECTION_OUT) ? XUSBPS_EPCR_RXE_MASK : 0U) |
			   ((direction & XUSBPS_EP_DIRECTION_IN) ? XUSBPS_EPCR_TXE_MASK : 0U);
		regs[XUSBPS_EPCRn_OFFSET(ep) / 4U] |= mask;
		return;
	}
	if (direction & XUSBPS_EP_DIRECTION_OUT) out_disabled = 0;
	if (direction & XUSBPS_EP_DIRECTION_IN) in_disabled = 0;
}

void XUsbPs_EpUnStall(XUsbPs *instance, u8 ep, u8 direction)
{
	assert(instance == &usb && ep == 0U);
	assert(direction == (XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT));
	++unstall_count;
}

void XUsbPs_EpStall(XUsbPs *instance, u8 ep, u8 direction)
{
	assert(instance == &usb && ep == 0U);
	assert(direction == (XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT));
	++stall_count;
}

int XUsbPs_EpPrime(XUsbPs *instance, u8 ep, u8 direction)
{
	assert(instance == &usb);
	if (ep == 0U && (direction & XUSBPS_EP_DIRECTION_OUT)) {
		if (fail_out_prime) return XST_FAILURE;
		++prime_out_count;
		regs[XUSBPS_EPPRIME_OFFSET / 4U] |= OUT0_BIT;
		return XST_SUCCESS;
	}
	if (ep == 0U && (direction & XUSBPS_EP_DIRECTION_IN)) {
		++prime_in_count;
		regs[XUSBPS_EPPRIME_OFFSET / 4U] |= IN0_BIT;
		return XST_SUCCESS;
	}
	return XST_SUCCESS;
}

int XUsbPs_BoundedRebuildEp0Out(XUsbPs *instance)
{
	unsigned i;
	XUsbPs_EpOut *out = &instance->DeviceConfig.Ep[0].Out;
	assert(instance == &usb && out_disabled && in_disabled);
	Xil_DCacheInvalidateRange((UINTPTR)out->dQH + 32U, 32U);
	Xil_DCacheInvalidateRange((UINTPTR)out->dQH, 32U);
	out->dQH->words[3] = 0U;
	out->dQH->words[1] = 0U;
	out->dQH->words[2] = 0U;
	out->dQH->words[4] = 0U;
	out->dQH->words[5] = 0U;
	out->dQH->words[6] = 0U;
	out->dQH->words[7] = 0U;
	Xil_DCacheFlushRange((UINTPTR)out->dQH, 32U);
	for (i = 0; i < instance->DeviceConfig.EpCfg[0].Out.NumBufs; ++i) {
		out->dTDs[i].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
		out->dTDs[i].active = 1U;
		out->dTDs[i].bptr[0] = (u32)(uintptr_t)out0_data[i];
		out->dTDs[i].next = &out->dTDs[(i + 1U) % instance->DeviceConfig.EpCfg[0].Out.NumBufs];
		out->dTDs[i].nlp = (u32)(uintptr_t)out->dTDs[i].next;
	}
	out->dTDCurr = out->dTDs;
	out->BufferPtr = out0_data[0];
	return XUsbPs_ReconfigureEp(instance, &instance->DeviceConfig, 0,
				     XUSBPS_EP_DIRECTION_OUT, 0);
}

int XUsbPs_ReconfigureEp(XUsbPs *instance, XUsbPs_DeviceConfig *config,
			 int ep, unsigned short direction, int direction_changed)
{
	unsigned i;
	(void)config; (void)direction_changed;
	assert(instance == &usb && ep == 0);
	if (direction == XUSBPS_EP_DIRECTION_OUT) {
		assert(out_disabled);
		assert(saw_exact_tail_invalidate);
		/* The SDK QH reinitializer touches only bytes 0..8 before its full
		 * structure flush; preserve BPTR4 and SETUP words in cache line 2. */
		assert(qh_slots[0].qh.words[8] != 0U);
		assert(qh_slots[0].qh.words[10] != 0U);
		assert(qh_slots[0].qh.words[11] != 0U);
		qh_slots[0].qh.words[0] |= 0x00080000U; /* IOS preserved */
		instance->DeviceConfig.Ep[0].Out.dTDCurr =
			instance->DeviceConfig.Ep[0].Out.dTDs;
		for (i = 0; i < instance->DeviceConfig.EpCfg[0].Out.NumBufs; ++i) {
			instance->DeviceConfig.Ep[0].Out.dTDs[i].active = 1U;
			instance->DeviceConfig.Ep[0].Out.dTDs[i].token =
				XUSBPS_dTDTOKEN_ACTIVE_MASK;
			instance->DeviceConfig.Ep[0].Out.dTDs[i].bptr[0] =
				(u32)(uintptr_t)out0_data[i];
		}
	} else if (direction == XUSBPS_EP_DIRECTION_IN) {
		unsigned i;
		assert(in_disabled);
		for (i = 0; i < instance->DeviceConfig.EpCfg[0].In.NumBufs; ++i) {
			in0_td[i].active = 0U;
			in0_td[i].token = 0U;
			in0_td[i].next = &in0_td[(i + 1U) % instance->DeviceConfig.EpCfg[0].In.NumBufs];
			in0_td[i].nlp = (u32)(uintptr_t)in0_td[i].next;
		}
		instance->DeviceConfig.Ep[0].In.dTDHead = in0_td;
		instance->DeviceConfig.Ep[0].In.dTDTail = in0_td;
		qh_slots[1].qh.words[0] |= 0x00080000U;
	} else {
		assert(0 && "unexpected endpoint direction");
	}
	return XST_SUCCESS;
}

int XUsbPs_EpBufferSend(XUsbPs *instance, u8 ep, const u8 *buffer, u32 len)
{
	assert(instance == &usb && ep == 0U);
	++send_count;
	last_send_buffer = buffer;
	last_send_length = len;
	if (fail_send) return XST_FAILURE;
	if (len != 0U) {
		XUsbPs_EpIn *in = &instance->DeviceConfig.Ep[0].In;
		XUsbPs_dTD *done = in->dTDHead;
		done->active = send_completes_immediately ? 0U : 1U;
		done->token = send_completes_immediately ? 0U : XUSBPS_dTDTOKEN_ACTIVE_MASK;
		done->userdata = (u32)(uintptr_t)buffer;
		in->dTDTail = done;
		in->dTDHead = XUsbPs_dTDGetNLP(done);
		if (!send_completes_immediately)
			regs[XUSBPS_EPPRIME_OFFSET / 4U] |= IN0_BIT;
		else
			regs[XUSBPS_EPCOMPL_OFFSET / 4U] |= IN0_BIT;
	}
	if (len == 0U)
		regs[XUSBPS_EPCOMPL_OFFSET / 4U] |= IN0_BIT;
	return XST_SUCCESS;
}

int XUsbPs_EpBufferReceive(XUsbPs *instance, u8 ep, u8 **buffer,
			   u32 *len, u32 *handle)
{
	assert(instance == &usb && ep == 0U);
	++receive_count;
	if (!rx_available) return XST_FAILURE;
	*buffer = rx_buffer;
	*len = rx_length;
	*handle = 0x1234U;
	rx_available = 0;
	return XST_SUCCESS;
}

void XUsbPs_EpBufferRelease(u32 handle)
{
	assert(handle == 0x1234U);
	++release_count;
}

void XUsbPs_SetDeviceAddress(XUsbPs *instance, u32 address)
{ (void)instance; (void)address; }
void XUsbPs_SetBits(XUsbPs *instance, u32 offset, u32 mask)
{ (void)instance; (void)offset; (void)mask; }
void XUsbPs_ClrBits(XUsbPs *instance, u32 offset, u32 mask)
{ (void)instance; (void)offset; (void)mask; }
int XUsbPs_EpDataBufferReceive(XUsbPs *instance, u8 ep, u8 *buffer, u32 len)
{ (void)instance; (void)ep; (void)buffer; (void)len; return XST_SUCCESS; }
int XUsbPs_EpGetData(XUsbPs *instance, u8 ep, u32 requested)
{ (void)instance; (void)ep; (void)requested; return XST_SUCCESS; }
XUsbPs_Config *XUsbPs_LookupConfig(u32 id)
{ (void)id; return NULL; }
int XUsbPs_CfgInitialize(XUsbPs *instance, void *config, uintptr_t address)
{ (void)instance; (void)config; (void)address; return XST_FAILURE; }
int XSetupInterruptSystem(XUsbPs *instance, void *handler, u32 id, u32 parent, u32 priority)
{ (void)instance; (void)handler; (void)id; (void)parent; (void)priority; return XST_FAILURE; }
int XUsbPs_ConfigureDevice(XUsbPs *instance, XUsbPs_DeviceConfig *config)
{ (void)instance; (void)config; return XST_FAILURE; }
int XUsbPs_EpSetHandler(XUsbPs *instance, u8 ep, u8 direction,
			XUsbPs_EpHandlerFunc handler, void *ref)
{ (void)instance; (void)ep; (void)direction; (void)handler; (void)ref; return XST_SUCCESS; }
void XUsbPs_IntrEnable(XUsbPs *instance, u32 mask)
{ (void)instance; (void)mask; }
void XUsbPs_Start(XUsbPs *instance) { (void)instance; }
void XTime_GetTime(XTime *value) { *value = 0U; }
int usleep(unsigned int usec) { (void)usec; return 0; }

static void run_interrupt(u32 epstat, u32 completion)
{
	regs[XUSBPS_ISR_OFFSET / 4U] = XUSBPS_IXR_UI_MASK;
	regs[XUSBPS_EPSTAT_OFFSET / 4U] = epstat;
	regs[XUSBPS_EPCOMPL_OFFSET / 4U] = completion;
	XUsbPs_IntrHandler(&usb);
}

static void test_setup_cancels_stale_out_and_latest_setup_wins(void)
{
	fixture_reset();
	set_setup(0x20U, 0x21U, 0U, 7U); /* stale SET_LINE_CODING */
	injected_setup = wire_setup;
	injected_setup.bRequest = 0x21U; /* GET_LINE_CODING replaces it in prepare */
	injected_setup.bmRequestType = 0xa1U;
	inject_setup_during_prepare = 1;
	inject_after_first_flush = 1;
	regs[XUSBPS_EPPRIME_OFFSET / 4U] = OUT0_BIT | IN0_BIT;
	out0_td[0].active = 0U; /* old OUT dTD completed with this same IRQ */
	out0_td[0].token = 0U;
	qh_slots[0].qh.words[8] = 0xabcdef20U;
	run_interrupt(1U, OUT0_BIT | IN0_BIT);
	assert(setup_reads == 2U);
	assert(receive_count == 0U && release_count == 0U);
	assert(prime_out_count == 1U);
	assert(send_count == 1U && last_send_length == 7U);
	assert(last_send_buffer == line_coding);
	assert(line_pending == 0);
	assert(saw_exact_tail_invalidate);
	assert(epcompl_ack_before_send >= 1U && epcompl_ack_after_send >= 1U);
	assert(qh_slots[0].qh.words[8] == 0xabcdef20U);
	assert(qh_slots[0].qh.words[10] == 0x000021a1U);
	assert(qh_slots[0].qh.words[11] == 0x00070000U);
	assert((regs[XUSBPS_EPCOMPL_OFFSET / 4U] & (OUT0_BIT | IN0_BIT)) == 0U);
}

static void test_set_line_receive_and_get_buffer_quiet_ownership(void)
{
	static const u8 initial[7] = {0x00, 0xc2, 0x01, 0x00, 0, 0, 8};
	static const u8 replacement[7] = {0x80, 0x25, 0x00, 0x00, 0, 0, 8};
	fixture_reset();
	memcpy(line_coding, initial, sizeof(initial));
	set_setup(0x20U, 0x21U, 0U, 7U);
	run_interrupt(1U, 0U);
	assert(line_pending == 1);
	assert(prime_out_count == 1U);
	assert(receive_count == 0U);
	memcpy(rx_buffer, replacement, sizeof(replacement));
	rx_length = 7U;
	rx_available = 1;
	ep0(&usb, 0U, XUSBPS_EP_EVENT_DATA_RX, NULL);
	assert(receive_count == 1U && release_count == 1U);
	assert(line_pending == 0);
	assert(memcmp(line_coding, replacement, sizeof(replacement)) == 0);
	assert(send_count == 1U && last_send_length == 0U);

	/* A GET reply owns the static line_coding array until a later SETUP has
	 * completed both bounded flushes.  The flush mock checks the snapshot. */
	fixture_reset();
	memcpy(line_coding, replacement, sizeof(replacement));
	send_completes_immediately = 0;
	set_setup(0x21U, 0xa1U, 0U, 7U);
	run_interrupt(1U, 0U);
	assert(send_count == 1U && last_send_buffer == line_coding);
	assert(last_send_length == 7U);
	assert(in0_td[0].active == 1U);
	memcpy(stale_line_coding_snapshot, line_coding, sizeof(line_coding));
	stale_line_coding_owned = 1;
	set_setup(0x20U, 0x21U, 0U, 7U);
	run_interrupt(1U, 0U);
	assert(memcmp(line_coding, stale_line_coding_snapshot,
		      sizeof(stale_line_coding_snapshot)) == 0);
	assert(line_pending == 1);
	assert(prime_out_count == 2U);
	stale_line_coding_owned = 0;
	memcpy(rx_buffer, initial, sizeof(initial));
	rx_length = 7U;
	rx_available = 1;
	ep0(&usb, 0U, XUSBPS_EP_EVENT_DATA_RX, NULL);
	assert(memcmp(line_coding, initial, sizeof(initial)) == 0);
}

static void test_failure_masks_ep0_but_dispatches_other_endpoints(void)
{
	fixture_reset();
	set_setup(0x20U, 0x21U, 0U, 7U);
	regs[XUSBPS_EPPRIME_OFFSET / 4U] = OUT0_BIT | IN0_BIT;
	fail_out_flush = 1;
	out0_td[0].active = 1U;
	in0_td[0].active = 1U;
	in0_td[0].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
	/* A simultaneous EP0 stale OUT/IN completion must be acknowledged but
	 * locally suppressed; EP1 RX/TX from this IRQ still run. */
	out1_td[0].active = 0U;
	out1_td[1].active = 1U;
	out1_td[1].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
	in1_td[0].active = 0U;
	in1_td[1].active = 1U;
	in1_td[1].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
	run_interrupt(1U, OUT0_BIT | IN0_BIT | OUT1_BIT | IN1_BIT);
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(receive_count == 0U && send_count == 0U);
	assert(prime_out_count == 0U);
	assert(ep1_rx_count == 1U && ep1_tx_count == 1U);
	assert(regs[XUSBPS_EPCOMPL_OFFSET / 4U] == 0U);

	/* Sticky faults also suppress EP0 completion-only work in a later ISR. */
	fail_out_flush = 0;
	usb.DeviceConfig.Ep[1].Out.dTDCurr = out1_td;
	usb.DeviceConfig.Ep[1].In.dTDHead = in1_td;
	usb.DeviceConfig.Ep[1].In.dTDTail = in1_td;
	out1_td[0].active = 0U;
	out1_td[1].active = 1U;
	out1_td[1].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
	in1_td[0].active = 0U;
	in1_td[1].active = 1U;
	in1_td[1].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
	run_interrupt(0U, OUT0_BIT | IN0_BIT | OUT1_BIT | IN1_BIT);
	assert(receive_count == 0U && send_count == 0U);
	assert(prime_out_count == 0U);
	assert(ep1_rx_count == 2U && ep1_tx_count == 2U);
	assert(regs[XUSBPS_EPCOMPL_OFFSET / 4U] == 0U);
}

static void test_failed_send_latches_then_next_setup_recovers(void)
{
	fixture_reset();
	set_setup(0x21U, 0xa1U, 0U, 7U); /* GET_LINE_CODING */
	fail_send = 1;
	run_interrupt(1U, 0U);
	assert(send_count == 1U);
	assert(stall_count >= 1U);
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(prime_out_count == 0U);

	fail_send = 0;
	set_setup(0x20U, 0x21U, 0U, 7U); /* legal SET_LINE_CODING clears old fault */
	run_interrupt(1U, 0U);
	assert(!XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(line_pending == 1);
	assert(prime_out_count == 1U);
	assert(unstall_count >= 1U);
}

static void test_data_rearm_prime_busy_preserves_descriptors(void)
{
	const u32 mask = OUT1_BIT | IN1_BIT | (1U << 18U);
	fixture_reset();
	prime_stuck = 1;
	regs[XUSBPS_EPPRIME_OFFSET / 4U] = mask;
	out1_td[0].active = 1U;
	out1_td[0].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
	in1_td[0].active = 1U;
	in1_td[0].token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
	qh_slots[2].qh.words[0] = 0x12345678U;
	qh_slots[3].qh.words[0] = 0x87654321U;
	assert(eye_usb_rearm_data(&usb, 0) != 0);
	assert(regs[XUSBPS_EPFLUSH_OFFSET / 4U] == 0U);
	assert((regs[XUSBPS_EPPRIME_OFFSET / 4U] & mask) == mask);
	assert(regs[XUSBPS_EPCOMPL_OFFSET / 4U] == 0U);
	assert(out1_td[0].active == 1U && out1_td[0].token == XUSBPS_dTDTOKEN_ACTIVE_MASK);
	assert(in1_td[0].active == 1U && in1_td[0].token == XUSBPS_dTDTOKEN_ACTIVE_MASK);
	assert(qh_slots[2].qh.words[0] == 0x12345678U);
	assert(qh_slots[3].qh.words[0] == 0x87654321U);
	assert(cache_invalidate_count == 0U && cache_flush_count == 0U);
}

static void test_standard_get_status_and_set_sel_error_route(void)
{
	XUsbPs_SetupData request;
	fixture_reset();
	memset(&request, 0, sizeof(request));
	request.bRequest = XUSBPS_REQ_GET_STATUS;
	request.bmRequestType = XUSBPS_STATUS_DEVICE;
	request.wLength = 2U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 1U && stall_count == 0U);
	assert(!XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(last_send_buffer != NULL && last_send_length == 2U);
	assert(((const u8 *)last_send_buffer)[0] == 1U);
	assert(((const u8 *)last_send_buffer)[1] == 0U);
	request.bRequest = XUSBPS_REQ_SET_ISOCH_DELAY;
	request.wLength = 0U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 1U && stall_count == 0U);

	request.bRequest = XUSBPS_REQ_SET_SEL;
	request.bmRequestType = XUSBPS_CMD_STDREQ;
	request.wLength = 6U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
	assert(receive_count == 1U);
	assert(stall_count == 1U);

	/* A standard reply send failure takes the same sticky-fault and stall
	 * route as a CDC class reply. */
	ring_init(in0_td, 4U, 0);
	usb.DeviceConfig.Ep[0].In.dTDHead = in0_td;
	usb.DeviceConfig.Ep[0].In.dTDTail = in0_td;
	regs[XUSBPS_EPPRIME_OFFSET / 4U] = 0U;
	request.bRequest = XUSBPS_REQ_GET_STATUS;
	request.bmRequestType = XUSBPS_STATUS_DEVICE;
	fail_send = 1;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(stall_count == 2U);
}

int main(void)
{
	test_setup_cancels_stale_out_and_latest_setup_wins();
	test_set_line_receive_and_get_buffer_quiet_ownership();
	test_failure_masks_ep0_but_dispatches_other_endpoints();
	test_failed_send_latches_then_next_setup_recovers();
	test_standard_get_status_and_set_sel_error_route();
	test_data_rearm_prime_busy_preserves_descriptors();
	puts("USB bounded generated intr/probe runtime mock: PASS 5/5");
	return 0;
}
