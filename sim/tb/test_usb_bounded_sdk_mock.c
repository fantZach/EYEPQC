#include <assert.h>
#include <stdint.h>
#include <stdio.h>

typedef uint32_t u32;
typedef uint8_t u8;
#define XST_SUCCESS 0
#define XST_FAILURE 1
#define XUSBPS_CMD_OFFSET 0x100U
#define XUSBPS_EPRDY_OFFSET 0x104U
#define XUSBPS_EPFLUSH_OFFSET 0x108U
#define XUSBPS_EPPRIME_OFFSET 0x10cU
#define XUSBPS_EPCOMPL_OFFSET 0x110U
#define XUSBPS_CMD_ATDTW_MASK 0x4000U
#define XUSBPS_EP_DIRECTION_OUT 1U
#define XUSBPS_EP_DIRECTION_IN 2U
#define XUSBPS_EPFLUSH_TX_SHIFT 16U
#define XUSBPS_EPCRn_OFFSET(n) (0x120U + ((n) * 4U))
#define XUSBPS_EPCR_TXE_MASK 0x00800000U
#define XUSBPS_EPCR_RXE_MASK 0x00000080U
#define XUSBPS_BOUNDED_POLL_LIMIT 32U

typedef struct { uintptr_t BaseAddress; } MockConfig;
typedef struct { u32 active; } XUsbPs_dTD;
typedef struct { XUsbPs_dTD *dTDHead; XUsbPs_dTD *dTDTail; } XUsbPs_EpIn;
typedef struct { XUsbPs_EpIn In; } XUsbPs_Ep;
typedef struct { XUsbPs_Ep Ep[1]; } XUsbPs_DeviceConfig;
typedef struct { MockConfig Config; XUsbPs_DeviceConfig DeviceConfig; } XUsbPs;

static u32 cmd_reg, ready_reg, active_status_reg, prime_reg, flush_reg, completion_reg;
static u32 cmd_reads, epflush_reads, prime_reads, active_status_reads;
static u32 flush_writes, disable_order, epcr_read_order, flush_order, epcr_reg, mock_order;
static int deny_tripwire, reset_preempts, flush_stuck, disabled, disable_stuck;
static int prime_stuck, completion_stuck;
static u32 active_clear_after;
static u32 completion_write;
static unsigned descriptor_sentinel = 0x51a7U;

static u32 XUsbPs_ReadReg(uintptr_t base, u32 offset);
static void XUsbPs_WriteReg(uintptr_t base, u32 offset, u32 value);
#define XUsbPs_EpFlush(instance, ep, dir) do { (void)(instance); (void)(dir); flush_reg = (1U << ((ep) + XUSBPS_EPFLUSH_TX_SHIFT)); ++flush_writes; flush_order = ++mock_order; } while (0)
#define XUsbPs_EpDisable(instance, ep, dir) do { (void)(instance); (void)(ep); disabled = 1; disable_order = ++mock_order; if (!disable_stuck) epcr_reg &= ~(((dir) & XUSBPS_EP_DIRECTION_OUT ? XUSBPS_EPCR_RXE_MASK : 0U) | ((dir) & XUSBPS_EP_DIRECTION_IN ? XUSBPS_EPCR_TXE_MASK : 0U)); } while (0)
#define XUSBPS_BOUNDED_POLICY_NO_CH9 1
#include "usb_bounded_sdk_policy.h"

static u32 XUsbPs_ReadReg(uintptr_t base, u32 offset)
{
	(void)base;
	switch (offset) {
	case XUSBPS_CMD_OFFSET: ++cmd_reads; return cmd_reg;
	case XUSBPS_EPRDY_OFFSET:
		++active_status_reads;
		return ready_reg | ((active_clear_after != 0U &&
			active_status_reads > active_clear_after) ? 0U : active_status_reg);
	case XUSBPS_EPCRn_OFFSET(1): epcr_read_order = ++mock_order; return epcr_reg;
	case XUSBPS_EPFLUSH_OFFSET:
		++epflush_reads;
		if (!flush_stuck && epflush_reads > 1U) flush_reg = 0U;
		return flush_reg;
	case XUSBPS_EPPRIME_OFFSET:
		++prime_reads;
		if (!prime_stuck && prime_reads > 1U) prime_reg = 0U;
		return prime_reg;
	case XUSBPS_EPCOMPL_OFFSET: return completion_reg;
	default: assert(0); return 0;
	}
}

static void XUsbPs_WriteReg(uintptr_t base, u32 offset, u32 value)
{
	(void)base;
	if (offset == XUSBPS_EPCOMPL_OFFSET) {
		completion_write |= value;
		if (!completion_stuck) completion_reg &= ~value;
		return;
	}
	assert(offset == XUSBPS_CMD_OFFSET);
	if ((value & XUSBPS_CMD_ATDTW_MASK) && (deny_tripwire || reset_preempts)) {
		cmd_reg = value & ~XUSBPS_CMD_ATDTW_MASK;
	} else {
		cmd_reg = value;
	}
}

static void reset_mock(void)
{
	cmd_reg = ready_reg = active_status_reg = prime_reg = flush_reg = completion_reg = 0U;
	epcr_reg = XUSBPS_EPCR_TXE_MASK | XUSBPS_EPCR_RXE_MASK;
	cmd_reads = epflush_reads = prime_reads = active_status_reads = 0U;
	flush_writes = disable_order = epcr_read_order = flush_order = mock_order = 0U;
	deny_tripwire = reset_preempts = flush_stuck = disabled = disable_stuck = 0;
	prime_stuck = completion_stuck = 0;
	active_clear_after = 0U;
	completion_write = 0U;
	descriptor_sentinel = 0x51a7U;
}

static void test_tripwire_success(void)
{
	XUsbPs usb = {0};
	u32 ready = 99U;
	reset_mock(); ready_reg = 0x4U;
	assert(XUsbPs_BoundedTripwireSample(&usb, 0x4U, &ready) == XST_SUCCESS);
	assert(ready == 0x4U);
	assert((cmd_reg & XUSBPS_CMD_ATDTW_MASK) == 0U);
	assert(cmd_reads < XUSBPS_BOUNDED_POLL_LIMIT * 3U);
}

static void test_tripwire_stuck_low(void)
{
	XUsbPs usb = {0};
	u32 ready = 99U;
	reset_mock(); deny_tripwire = 1;
	assert(XUsbPs_BoundedTripwireSample(&usb, 0x4U, &ready) == XST_FAILURE);
	assert((cmd_reg & XUSBPS_CMD_ATDTW_MASK) == 0U);
	assert(cmd_reads <= (XUSBPS_BOUNDED_POLL_LIMIT * 2U) + 1U);
}

static void test_reset_preempts_tripwire(void)
{
	XUsbPs usb = {0};
	u32 ready = 99U;
	reset_mock(); reset_preempts = 1;
	assert(XUsbPs_BoundedTripwireSample(&usb, 0x4U, &ready) == XST_FAILURE);
	assert((cmd_reg & XUSBPS_CMD_ATDTW_MASK) == 0U);
	assert(cmd_reads <= (XUSBPS_BOUNDED_POLL_LIMIT * 2U) + 1U);
}

static void test_flush_failure_preserves_owned_chain(void)
{
	XUsbPs usb = {0};
	reset_mock(); flush_stuck = 1;
	assert(XUsbPs_BoundedQuiesceInEndpoint(&usb, 1U, 0x00020000U,
					       0x00020000U) == XST_FAILURE);
	assert(disabled == 1);
	assert(descriptor_sentinel == 0x51a7U);
	assert(epflush_reads <= XUSBPS_BOUNDED_POLL_LIMIT);
}

static void test_flush_success_preserves_chain_for_terminal_disable(void)
{
	XUsbPs usb = {0};
	reset_mock();
	assert(XUsbPs_BoundedQuiesceInEndpoint(&usb, 1U, 0x00020000U,
					       0x00020000U) == XST_SUCCESS);
	assert(disabled == 1);
	assert(descriptor_sentinel == 0x51a7U);
	assert(prime_reads > 0U);
}

static void test_secure_poll_limit_256(void)
{
	XUsbPs usb = {0};
	u32 flush_polls = 0U, prime_polls = 0U;
	reset_mock(); flush_stuck = 1;
	assert(XUsbPs_BoundedQuiesceInEndpointWithLimit(
		&usb, 1U, 0x00020000U, 0x00020000U, 256U,
		&flush_polls, &prime_polls) == XST_FAILURE);
	assert(flush_polls == 256U && prime_polls == 0U && epflush_reads == 256U);
	reset_mock(); prime_stuck = 1; prime_reg = 0x00020000U;
	assert(XUsbPs_BoundedQuiesceInEndpointWithLimit(
		&usb, 1U, 0x00020000U, 0x00020000U, 256U,
		&flush_polls, &prime_polls) == XST_FAILURE);
	assert(flush_polls == 2U && prime_polls == 256U && prime_reads == 256U);
	reset_mock();
	assert(XUsbPs_BoundedQuiesceInEndpointWithLimit(
		&usb, 1U, 0x00020000U, 0x00020000U, 256U,
		&flush_polls, &prime_polls) == XST_SUCCESS);
	assert(flush_polls == 2U && prime_polls == 1U &&
	       flush_polls <= 256U && prime_polls <= 256U);
}

static void test_status_gate_reflushes_and_is_bounded(void)
{
	XUsbPs usb = {0};
	u32 flush_polls = 0U, prime_polls = 0U, active_polls = 0U, active_status = 0U;
	reset_mock(); active_status_reg = 0x00020000U; active_clear_after = 2U;
	assert(XUsbPs_BoundedQuiesceInEndpointWithStatusWithLimit(
		&usb, 1U, 0x00020000U, 0x00020000U, 16U,
		&flush_polls, &prime_polls, &active_polls, &active_status) == XST_SUCCESS);
	assert(active_polls == 3U && active_status == 0U && flush_writes == 3U);
	assert(flush_polls == 4U && prime_polls == 3U);
	assert(disable_order != 0U && epcr_read_order > disable_order &&
	       flush_order > epcr_read_order);

	reset_mock(); active_status_reg = 0x00020000U;
	assert(XUsbPs_BoundedQuiesceInEndpointWithStatusWithLimit(
		&usb, 1U, 0x00020000U, 0x00020000U, 4U,
		&flush_polls, &prime_polls, &active_polls, &active_status) == XST_FAILURE);
	assert(active_polls == 3U && active_status == 0x00020000U);
	assert(flush_writes == 3U && descriptor_sentinel == 0x51a7U);
}

static void test_disable_readback_prevents_flush(void)
{
	XUsbPs usb = {0};
	reset_mock(); disable_stuck = 1;
	assert(XUsbPs_BoundedQuiesceInEndpointWithStatusWithLimit(
		&usb, 1U, 0x00020000U, 0x00020000U, 16U,
		NULL, NULL, NULL, NULL) == XST_FAILURE);
	assert(disabled && flush_writes == 0U && epflush_reads == 0U);
}

static void test_status_output_is_not_zero_when_unobserved(void)
{
	XUsbPs usb = {0};
	u32 flush_polls = 0U, prime_polls = 0U, active_polls = 0U;
	u32 active_status = 0U;
	reset_mock(); flush_stuck = 1;
	assert(XUsbPs_BoundedQuiesceInEndpointWithStatusWithLimit(
		&usb, 1U, 0x00020000U, 0x00020000U, 4U,
		&flush_polls, &prime_polls, &active_polls, &active_status) == XST_FAILURE);
	assert(flush_polls == 4U && prime_polls == 0U && active_polls == 0U);
	assert(active_status == 0xffffffffU);
}

static void test_clear_only_old_ep1_in_completion(void)
{
	XUsbPs usb = {0};
	const u32 in_mask = 1U << 17U;
	const u32 unrelated = (1U << 16U) | 1U;
	reset_mock(); completion_reg = in_mask | unrelated;
	assert(XUsbPs_BoundedClearEndpointCompletion(&usb, in_mask) == XST_SUCCESS);
	assert(completion_write == in_mask && completion_reg == unrelated);
	reset_mock(); completion_reg = in_mask; completion_stuck = 1;
	assert(XUsbPs_BoundedClearEndpointCompletion(&usb, in_mask) == XST_FAILURE);
	assert(completion_write == in_mask && completion_reg == in_mask);
}

int main(void)
{
	test_tripwire_success();
	test_tripwire_stuck_low();
	test_reset_preempts_tripwire();
	test_flush_failure_preserves_owned_chain();
	test_flush_success_preserves_chain_for_terminal_disable();
	test_secure_poll_limit_256();
	test_status_gate_reflushes_and_is_bounded();
	test_disable_readback_prevents_flush();
	test_status_output_is_not_zero_when_unobserved();
	test_clear_only_old_ep1_in_completion();
	puts("usb bounded SDK register mocks: PASS");
	return 0;
}
