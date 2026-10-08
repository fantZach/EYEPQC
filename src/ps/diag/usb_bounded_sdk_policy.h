#ifndef EYEPQC_USB_BOUNDED_SDK_POLICY_H
#define EYEPQC_USB_BOUNDED_SDK_POLICY_H

/* Small, ISR-safe polling primitives shared by the generated XUsbPs overlay
 * and its register-mock test.  No wall clock, scheduler, or interrupt wait is
 * used: each call has a fixed upper bound on register reads. */
#ifndef XUSBPS_BOUNDED_POLL_LIMIT
#define XUSBPS_BOUNDED_POLL_LIMIT 4096U
#endif

/* Implemented by the patched endpoint translation unit so Chapter 9 and the
 * queue path share one sticky per-controller fault state. */
void XUsbPs_BoundedMarkEndpointFaulted(XUsbPs *InstancePtr, u8 EpNum);
int XUsbPs_BoundedEndpointIsFaulted(XUsbPs *InstancePtr, u8 EpNum);
/* Call only after a controller reset and independent proof that DMA is idle. */
void XUsbPs_BoundedClearEndpointFaults(XUsbPs *InstancePtr);

static inline int XUsbPs_BoundedTripwireSample(XUsbPs *InstancePtr, u32 BitMask,
					 u32 *ReadyValue)
{
	u32 Poll;
	u32 RegValue;
	u32 Ready;

	for (Poll = 0; Poll < XUSBPS_BOUNDED_POLL_LIMIT; ++Poll) {
		RegValue = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
					  XUSBPS_CMD_OFFSET);
		XUsbPs_WriteReg(InstancePtr->Config.BaseAddress, XUSBPS_CMD_OFFSET,
				RegValue | XUSBPS_CMD_ATDTW_MASK);
		Ready = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
				       XUSBPS_EPRDY_OFFSET) & BitMask;
		RegValue = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
					  XUSBPS_CMD_OFFSET);
		if (RegValue & XUSBPS_CMD_ATDTW_MASK) {
			XUsbPs_WriteReg(InstancePtr->Config.BaseAddress,
					XUSBPS_CMD_OFFSET,
					RegValue & ~XUSBPS_CMD_ATDTW_MASK);
			*ReadyValue = Ready;
			return XST_SUCCESS;
		}
	}

	/* Clear a possibly latched tripwire even on failure.  Caller must treat
	 * the already-built dTD chain as owned by the controller until quiesced. */
	RegValue = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
				  XUSBPS_CMD_OFFSET);
	XUsbPs_WriteReg(InstancePtr->Config.BaseAddress, XUSBPS_CMD_OFFSET,
			RegValue & ~XUSBPS_CMD_ATDTW_MASK);
	return XST_FAILURE;
}

/* The request builder has already attached and activated descriptors when the
 * ATDTW check runs.  Never roll those fields back speculatively.  A completed
 * flush plus a clear PRIME bit is the only success condition for declaring
 * the endpoint quiescent; the endpoint is disabled either way. */
static inline int XUsbPs_BoundedQuiesceInEndpoint(XUsbPs *InstancePtr, u8 EpNum,
					    u32 PrimeMask, u32 FlushMask)
{
	u32 Poll;
	int FlushDone = 0;
	int PrimeClear = 0;

	XUsbPs_EpFlush(InstancePtr, EpNum, XUSBPS_EP_DIRECTION_IN);
	for (Poll = 0; Poll < XUSBPS_BOUNDED_POLL_LIMIT; ++Poll) {
		if ((XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
				    XUSBPS_EPFLUSH_OFFSET) & FlushMask) == 0U) {
			FlushDone = 1;
			break;
		}
	}
	if (FlushDone) {
		for (Poll = 0; Poll < XUSBPS_BOUNDED_POLL_LIMIT; ++Poll) {
			if ((XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
					    XUSBPS_EPPRIME_OFFSET) & PrimeMask) == 0U) {
				PrimeClear = 1;
				break;
			}
		}
	}

	XUsbPs_EpDisable(InstancePtr, EpNum, XUSBPS_EP_DIRECTION_IN);
	return (FlushDone && PrimeClear) ? XST_SUCCESS : XST_FAILURE;
}

#endif /* EYEPQC_USB_BOUNDED_SDK_POLICY_H */
