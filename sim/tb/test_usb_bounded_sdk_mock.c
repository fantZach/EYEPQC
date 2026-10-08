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
#define XUSBPS_CMD_ATDTW_MASK 0x4000U
#define XUSBPS_EP_DIRECTION_IN 2U
#define XUSBPS_EPFLUSH_TX_SHIFT 16U
#define XUSBPS_BOUNDED_POLL_LIMIT 32U

typedef struct { uintptr_t BaseAddress; } MockConfig;
typedef struct { MockConfig Config; } XUsbPs;

static u32 cmd_reg, ready_reg, prime_reg, flush_reg;
static u32 cmd_reads, epflush_reads, prime_reads;
static int deny_tripwire, reset_preempts, flush_stuck, disabled;
static unsigned descriptor_sentinel = 0x51a7U;

static u32 XUsbPs_ReadReg(uintptr_t base, u32 offset);
static void XUsbPs_WriteReg(uintptr_t base, u32 offset, u32 value);
#define XUsbPs_EpFlush(instance, ep, dir) do { (void)(instance); (void)(dir); flush_reg = (1U << ((ep) + XUSBPS_EPFLUSH_TX_SHIFT)); } while (0)
#define XUsbPs_EpDisable(instance, ep, dir) do { (void)(instance); (void)(ep); (void)(dir); disabled = 1; } while (0)
#include "usb_bounded_sdk_policy.h"

static u32 XUsbPs_ReadReg(uintptr_t base, u32 offset)
{
	(void)base;
	switch (offset) {
	case XUSBPS_CMD_OFFSET: ++cmd_reads; return cmd_reg;
	case XUSBPS_EPRDY_OFFSET: return ready_reg;
	case XUSBPS_EPFLUSH_OFFSET:
		++epflush_reads;
		if (!flush_stuck && epflush_reads > 1U) flush_reg = 0U;
		return flush_reg;
	case XUSBPS_EPPRIME_OFFSET: ++prime_reads; return prime_reg;
	default: assert(0); return 0;
	}
}

static void XUsbPs_WriteReg(uintptr_t base, u32 offset, u32 value)
{
	(void)base;
	assert(offset == XUSBPS_CMD_OFFSET);
	if ((value & XUSBPS_CMD_ATDTW_MASK) && (deny_tripwire || reset_preempts)) {
		cmd_reg = value & ~XUSBPS_CMD_ATDTW_MASK;
	} else {
		cmd_reg = value;
	}
}

static void reset_mock(void)
{
	cmd_reg = ready_reg = prime_reg = flush_reg = 0U;
	cmd_reads = epflush_reads = prime_reads = 0U;
	deny_tripwire = reset_preempts = flush_stuck = disabled = 0;
	descriptor_sentinel = 0x51a7U;
}

static void test_tripwire_success(void)
{
	XUsbPs usb = {{0}};
	u32 ready = 99U;
	reset_mock(); ready_reg = 0x4U;
	assert(XUsbPs_BoundedTripwireSample(&usb, 0x4U, &ready) == XST_SUCCESS);
	assert(ready == 0x4U);
	assert((cmd_reg & XUSBPS_CMD_ATDTW_MASK) == 0U);
	assert(cmd_reads < XUSBPS_BOUNDED_POLL_LIMIT * 3U);
}

static void test_tripwire_stuck_low(void)
{
	XUsbPs usb = {{0}};
	u32 ready = 99U;
	reset_mock(); deny_tripwire = 1;
	assert(XUsbPs_BoundedTripwireSample(&usb, 0x4U, &ready) == XST_FAILURE);
	assert((cmd_reg & XUSBPS_CMD_ATDTW_MASK) == 0U);
	assert(cmd_reads <= (XUSBPS_BOUNDED_POLL_LIMIT * 2U) + 1U);
}

static void test_reset_preempts_tripwire(void)
{
	XUsbPs usb = {{0}};
	u32 ready = 99U;
	reset_mock(); reset_preempts = 1;
	assert(XUsbPs_BoundedTripwireSample(&usb, 0x4U, &ready) == XST_FAILURE);
	assert((cmd_reg & XUSBPS_CMD_ATDTW_MASK) == 0U);
	assert(cmd_reads <= (XUSBPS_BOUNDED_POLL_LIMIT * 2U) + 1U);
}

static void test_flush_failure_preserves_owned_chain(void)
{
	XUsbPs usb = {{0}};
	reset_mock(); flush_stuck = 1;
	assert(XUsbPs_BoundedQuiesceInEndpoint(&usb, 1U, 0x00020000U,
					       0x00020000U) == XST_FAILURE);
	assert(disabled == 1);
	assert(descriptor_sentinel == 0x51a7U);
	assert(epflush_reads <= XUSBPS_BOUNDED_POLL_LIMIT);
}

static void test_flush_success_preserves_chain_for_terminal_disable(void)
{
	XUsbPs usb = {{0}};
	reset_mock();
	assert(XUsbPs_BoundedQuiesceInEndpoint(&usb, 1U, 0x00020000U,
					       0x00020000U) == XST_SUCCESS);
	assert(disabled == 1);
	assert(descriptor_sentinel == 0x51a7U);
	assert(prime_reads > 0U);
}

int main(void)
{
	test_tripwire_success();
	test_tripwire_stuck_low();
	test_reset_preempts_tripwire();
	test_flush_failure_preserves_owned_chain();
	test_flush_success_preserves_chain_for_terminal_disable();
	puts("usb bounded SDK register mocks: PASS");
	return 0;
}
