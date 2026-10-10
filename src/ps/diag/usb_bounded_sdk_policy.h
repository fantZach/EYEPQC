#ifndef EYEPQC_USB_BOUNDED_SDK_POLICY_H
#define EYEPQC_USB_BOUNDED_SDK_POLICY_H

#include "xusbps_endpoint.h"

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
/* Clear all sticky bits only after full controller reset and global DMA idle. */
void XUsbPs_BoundedClearEndpointFaults(XUsbPs *InstancePtr);
/* Clear one bit only after that endpoint's bounded flush and ring rebuild. */
void XUsbPs_BoundedClearEndpointFault(XUsbPs *InstancePtr, u8 EpNum);
int XUsbPs_BoundedRebuildEp0Out(XUsbPs *InstancePtr);
static inline int XUsbPs_BoundedQuiesceInEndpoint(XUsbPs *InstancePtr, u8 EpNum,
							  u32 PrimeMask, u32 FlushMask);
static inline int XUsbPs_BoundedQuiesceEndpoint(XUsbPs *InstancePtr, u8 EpNum,
							u8 Direction, u32 PrimeMask,
							u32 FlushMask);

#ifndef XUSBPS_BOUNDED_POLICY_NO_CH9
typedef struct {
	volatile u32 setup_count;
	volatile u32 recovery_count;
	volatile u32 failure_count;
	volatile u32 last_reason;
	volatile u32 last_request;
	volatile u32 last_request_type;
	volatile u32 last_head;
	volatile u32 last_tail;
	volatile u32 last_head_token;
	volatile u32 last_tail_token;
	volatile u32 last_out_curr;
	volatile u32 last_out_token;
	volatile u32 last_prime;
	volatile u32 last_flush;
	volatile u32 last_out_prime;
	volatile u32 last_out_flush;
	volatile u32 last_result;
} XUsbPs_Ch9OwnershipDiag;

extern volatile XUsbPs_Ch9OwnershipDiag XUsbPs_Ch9OwnershipDiagnostics;

#define XUSBPS_CH9_OWNERSHIP_STICKY       0x01U
#define XUSBPS_CH9_OWNERSHIP_QUEUE        0x02U
#define XUSBPS_CH9_OWNERSHIP_ACTIVE       0x04U
#define XUSBPS_CH9_OWNERSHIP_PRIMED       0x08U
#define XUSBPS_CH9_OWNERSHIP_BAD_RING     0x10U
#define XUSBPS_CH9_OWNERSHIP_FLUSH_FAILED 0x20U
#define XUSBPS_CH9_OWNERSHIP_REBUILD_FAIL 0x40U
#define XUSBPS_CH9_OWNERSHIP_SETUP_CANCEL 0x80U

/* Chapter 9 reply arrays are static DMA buffers.  Treat any unretired EP0 IN
 * descriptor, active head descriptor, or active prime bit as still owned.
 * The SDK retires dTDs in its TX-completion handler; SETUP dispatch itself
 * does not flush or retire EP0 IN requests. */
static inline int XUsbPs_Ch9ReplyBufferWritable(XUsbPs *InstancePtr)
{
	XUsbPs_EpIn *Ep;
	u32 PrimeMask = 1U << XUSBPS_EPFLUSH_TX_SHIFT;

	if (InstancePtr == NULL) {
		return XST_FAILURE;
	}
	Ep = &InstancePtr->DeviceConfig.Ep[0].In;
	if (Ep->dTDHead == NULL || Ep->dTDTail == NULL) {
		return XST_FAILURE;
	}
	XUsbPs_dTDInvalidateCache(Ep->dTDHead);
	if (Ep->dTDTail != Ep->dTDHead || XUsbPs_dTDIsActive(Ep->dTDHead) ||
	    (XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
			    XUSBPS_EPPRIME_OFFSET) & PrimeMask) != 0U) {
		return XST_FAILURE;
	}
	return XST_SUCCESS;
}

/* A new SETUP aborts the previous EP0 control transfer in both directions.
 * The SDK invokes the SETUP callback before processing completion bits, so
 * neither EP0 ring or static buffer can be reused until both queues are
 * quiescent, canceled completions are cleared, and the rings are rebuilt. */
static inline int XUsbPs_BoundedPrepareEp0Setup(XUsbPs *InstancePtr,
							 XUsbPs_SetupData *SetupData)
{
	XUsbPs_EpIn *Ep;
	XUsbPs_EpOut *Out;
	u32 InPrimeMask = 1U << XUSBPS_EPFLUSH_TX_SHIFT;
	u32 InFlushMask = InPrimeMask;
	u32 OutPrimeMask = 1U;
	u32 OutFlushMask = 1U;
	u32 InPrime;
	u32 InFlush;
	u32 OutPrime;
	u32 OutFlush;
	u32 Index;
	u32 Field;
	int OutStatus;
	int InStatus;
	u32 CompletionMask = OutPrimeMask | InPrimeMask;
	XUsbPs_SetupData InitialSetup;

	if (InstancePtr == NULL || SetupData == NULL)
		return XST_FAILURE;
	++XUsbPs_Ch9OwnershipDiagnostics.setup_count;
	XUsbPs_Ch9OwnershipDiagnostics.last_reason = XUSBPS_CH9_OWNERSHIP_SETUP_CANCEL;
	Ep = &InstancePtr->DeviceConfig.Ep[0].In;
	Out = &InstancePtr->DeviceConfig.Ep[0].Out;
	/* Validate the QH and rings before the SDK SETUP reader can dereference a
	 * malformed queue pointer. */
	if (Ep->dTDHead == NULL || Ep->dTDTail == NULL || Ep->dTDs == NULL ||
	    Ep->dQH == NULL || Out->dTDCurr == NULL || Out->dTDs == NULL ||
	    Out->dQH == NULL || InstancePtr->DeviceConfig.EpCfg[0].In.NumBufs == 0U ||
	    InstancePtr->DeviceConfig.EpCfg[0].Out.NumBufs == 0U ||
	    (((UINTPTR)Out->dQH) & 63U) != 0U || sizeof(*Out->dQH) != XUSBPS_dQH_ALIGN)
		goto bad_ring;
	/* Snapshot before touching either QH. EpGetSetupData uses the SDK SUTW
	 * tripwire; a second call after rebuilding selects a newer SETUP if the host
	 * replaced this one while the bounded cancellation was in progress. */
	if (XUsbPs_EpGetSetupData(InstancePtr, 0U, &InitialSetup) != XST_SUCCESS)
		goto fail;
	XUsbPs_Ch9OwnershipDiagnostics.last_request = InitialSetup.bRequest;
	XUsbPs_Ch9OwnershipDiagnostics.last_request_type = InitialSetup.bmRequestType;
	InPrime = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
				 XUSBPS_EPPRIME_OFFSET) & InPrimeMask;
	InFlush = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
				XUSBPS_EPFLUSH_OFFSET) & InFlushMask;
	OutPrime = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
				  XUSBPS_EPPRIME_OFFSET) & OutPrimeMask;
	OutFlush = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
				 XUSBPS_EPFLUSH_OFFSET) & OutFlushMask;
	XUsbPs_Ch9OwnershipDiagnostics.last_prime = InPrime;
	XUsbPs_Ch9OwnershipDiagnostics.last_flush = InFlush;
	XUsbPs_Ch9OwnershipDiagnostics.last_out_prime = OutPrime;
	XUsbPs_Ch9OwnershipDiagnostics.last_out_flush = OutFlush;
	XUsbPs_Ch9OwnershipDiagnostics.last_head = (u32)(UINTPTR)Ep->dTDHead;
	XUsbPs_Ch9OwnershipDiagnostics.last_tail = (u32)(UINTPTR)Ep->dTDTail;
	if (Ep->dTDHead != NULL) {
		XUsbPs_dTDInvalidateCache(Ep->dTDHead);
		XUsbPs_Ch9OwnershipDiagnostics.last_head_token =
			XUsbPs_ReaddTD(Ep->dTDHead, XUSBPS_dTDTOKEN);
	} else {
		XUsbPs_Ch9OwnershipDiagnostics.last_head_token = 0xffffffffU;
	}
	if (Ep->dTDTail != NULL) {
		XUsbPs_dTDInvalidateCache(Ep->dTDTail);
		XUsbPs_Ch9OwnershipDiagnostics.last_tail_token =
			XUsbPs_ReaddTD(Ep->dTDTail, XUSBPS_dTDTOKEN);
	} else {
		XUsbPs_Ch9OwnershipDiagnostics.last_tail_token = 0xffffffffU;
	}
	XUsbPs_Ch9OwnershipDiagnostics.last_out_curr = (u32)(UINTPTR)Out->dTDCurr;
	if (Out->dTDCurr != NULL) {
		XUsbPs_dTDInvalidateCache(Out->dTDCurr);
		XUsbPs_Ch9OwnershipDiagnostics.last_out_token =
			XUsbPs_ReaddTD(Out->dTDCurr, XUSBPS_dTDTOKEN);
	} else {
		XUsbPs_Ch9OwnershipDiagnostics.last_out_token = 0xffffffffU;
	}

	(void)InPrime; (void)InFlush; (void)OutPrime; (void)OutFlush;
	OutStatus = XUsbPs_BoundedQuiesceEndpoint(InstancePtr, 0U,
						 XUSBPS_EP_DIRECTION_OUT,
						 OutPrimeMask, OutFlushMask);
	InStatus = XUsbPs_BoundedQuiesceEndpoint(InstancePtr, 0U,
						XUSBPS_EP_DIRECTION_IN,
						InPrimeMask, InFlushMask);
	if (OutStatus != XST_SUCCESS || InStatus != XST_SUCCESS) {
		XUsbPs_Ch9OwnershipDiagnostics.last_reason =
			XUSBPS_CH9_OWNERSHIP_SETUP_CANCEL | XUSBPS_CH9_OWNERSHIP_FLUSH_FAILED;
		goto fail;
	}

	/* Both directions passed FLUSH deassertion plus PRIME clear, which is the
	 * DMA-idle proof. EP0 control enable bits are read-only on this controller;
	 * the disable calls above are best-effort and are not this proof. Clear old
	 * completions before rebuilding either ring or allowing a new prime. */
	XUsbPs_WriteReg(InstancePtr->Config.BaseAddress, XUSBPS_EPCOMPL_OFFSET,
			CompletionMask);
	if (XUsbPs_BoundedRebuildEp0Out(InstancePtr) != XST_SUCCESS)
		goto rebuild_fail;
	for (Index = 0U; Index < InstancePtr->DeviceConfig.EpCfg[0].In.NumBufs;
	     ++Index) {
		XUsbPs_dTD *Td = &Ep->dTDs[Index];
		XUsbPs_dTDInvalidateCache(Td);
		XUsbPs_WritedTD(Td, XUSBPS_dTDTOKEN, 0U);
		XUsbPs_WritedTD(Td, XUSBPS_dTDUSERDATA, 0U);
		for (Field = 0U; Field < 5U; ++Field)
		XUsbPs_WritedTD(Td, XUSBPS_dTDBPTR(Field), 0U);
		XUsbPs_dTDFlushCache(Td);
	}
	XUsbPs_dQHInvalidateCache(Ep->dQH);
	XUsbPs_WritedQH(Ep->dQH, XUSBPS_dQHCPTR, 0U);
	XUsbPs_WritedQH(Ep->dQH, XUSBPS_dQHdTDNLP, 0U);
	XUsbPs_WritedQH(Ep->dQH, XUSBPS_dQHdTDTOKEN, 0U);
	for (Field = 0U; Field < 5U; ++Field)
		XUsbPs_WritedQH(Ep->dQH, 0x10U + Field * 4U, 0U);
	XUsbPs_dQHFlushCache(Ep->dQH);
	if (XUsbPs_ReconfigureEp(InstancePtr, &InstancePtr->DeviceConfig, 0,
				 XUSBPS_EP_DIRECTION_IN, 0) != XST_SUCCESS)
		goto rebuild_fail;
	if (Out->dTDCurr != Out->dTDs ||
	    XUsbPs_Ch9ReplyBufferWritable(InstancePtr) != XST_SUCCESS)
		goto rebuild_fail;
	XUsbPs_EpEnable(InstancePtr, 0U, XUSBPS_EP_DIRECTION_OUT);
	XUsbPs_EpEnable(InstancePtr, 0U, XUSBPS_EP_DIRECTION_IN);
	XUsbPs_EpUnStall(InstancePtr, 0U,
			 XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
	XUsbPs_BoundedClearEndpointFault(InstancePtr, 0U);
	if (XUsbPs_EpGetSetupData(InstancePtr, 0U, SetupData) != XST_SUCCESS)
		goto rebuild_fail;
	++XUsbPs_Ch9OwnershipDiagnostics.recovery_count;
	XUsbPs_Ch9OwnershipDiagnostics.last_result = XST_SUCCESS;
	return XST_SUCCESS;

bad_ring:
	XUsbPs_Ch9OwnershipDiagnostics.last_reason = XUSBPS_CH9_OWNERSHIP_BAD_RING;
rebuild_fail:
	XUsbPs_Ch9OwnershipDiagnostics.last_reason |= XUSBPS_CH9_OWNERSHIP_REBUILD_FAIL;
fail:
	++XUsbPs_Ch9OwnershipDiagnostics.failure_count;
	XUsbPs_Ch9OwnershipDiagnostics.last_result = XST_FAILURE;
	XUsbPs_BoundedMarkEndpointFaulted(InstancePtr, 0U);
	XUsbPs_EpDisable(InstancePtr, 0U,
			 XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
	XUsbPs_EpStall(InstancePtr, 0U,
		       XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT);
	return XST_FAILURE;
}
#endif /* XUSBPS_BOUNDED_POLICY_NO_CH9 */

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
 * ATDTW check runs. Never roll those fields back speculatively. A successful
 * flush, clear PRIME, and inactive ENDPTSTAT readback are required before
 * touching descriptors. EP0 enable bits are read-only and exempt from disable
 * readback; their DMA ownership still requires all three status gates. */
static inline int XUsbPs_BoundedQuiesceEndpointWithLimit(
											XUsbPs *InstancePtr, u8 EpNum,
											u8 Direction, u32 PrimeMask,
											u32 FlushMask, u32 PollLimit,
											u32 *FlushPolls, u32 *PrimePolls);
static inline int XUsbPs_BoundedQuiesceEndpointWithStatusWithLimit(
											XUsbPs *InstancePtr, u8 EpNum,
											u8 Direction, u32 PrimeMask,
											u32 FlushMask, u32 PollLimit,
											u32 *FlushPolls, u32 *PrimePolls,
											u32 *ActivePolls, u32 *ActiveStatus);
static inline int XUsbPs_BoundedQuiesceInEndpointWithStatusWithLimit(
											XUsbPs *InstancePtr, u8 EpNum,
											u32 PrimeMask, u32 FlushMask,
											u32 PollLimit, u32 *FlushPolls,
											u32 *PrimePolls, u32 *ActivePolls,
											u32 *ActiveStatus);

static inline void XUsbPs_BoundedDsb(void)
{
#if defined(__arm__) && !defined(G6_USB_NATIVE_TEST)
	__asm__ volatile("dsb sy" ::: "memory");
#else
	__asm__ volatile("" ::: "memory");
#endif
}

/* Disable, flush, and confirm ENDPTSTAT inactive before callers touch any
 * descriptor or completion state. Flush/prime/status counters each have one
 * shared PollLimit across all re-flush attempts. ENDPTSTAT uses the same
 * endpoint-direction mask as FLUSH; active endpoints are de-primed again. */
static inline int XUsbPs_BoundedQuiesceEndpointWithStatusWithLimit(
											XUsbPs *InstancePtr, u8 EpNum,
											u8 Direction, u32 PrimeMask,
											u32 FlushMask, u32 PollLimit,
											u32 *FlushPolls, u32 *PrimePolls,
											u32 *ActivePolls, u32 *ActiveStatus)
{
	u32 F = 0U, P = 0U, A = 0U, Status = 0xffffffffU, DisableMask = 0U;
	int Result = XST_FAILURE;
	if (InstancePtr == NULL || PollLimit == 0U || PrimeMask == 0U ||
	    FlushMask == 0U || Direction == 0U) goto done;
	if ((Direction & XUSBPS_EP_DIRECTION_OUT) != 0U)
		DisableMask |= XUSBPS_EPCR_RXE_MASK;
	if ((Direction & XUSBPS_EP_DIRECTION_IN) != 0U)
		DisableMask |= XUSBPS_EPCR_TXE_MASK;
	if (DisableMask == 0U) goto done;
	XUsbPs_EpDisable(InstancePtr, EpNum, Direction);
	XUsbPs_BoundedDsb();
	/* EP0 enable bits are read-only. Endpoint 1+ must read back disabled before
	 * the controller is asked to de-prime their DMA queue. */
	if (EpNum != 0U &&
	    (XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
			    XUSBPS_EPCRn_OFFSET(EpNum)) & DisableMask) != 0U)
		goto done;
	while (F < PollLimit && P < PollLimit && A < PollLimit) {
		int FlushDone = 0, PrimeClear = 0;
		XUsbPs_EpFlush(InstancePtr, EpNum, Direction);
		while (F < PollLimit) {
			++F;
			if ((XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
					    XUSBPS_EPFLUSH_OFFSET) & FlushMask) == 0U) {
				FlushDone = 1;
				break;
			}
		}
		if (!FlushDone) break;
		while (P < PollLimit) {
			++P;
			if ((XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
					    XUSBPS_EPPRIME_OFFSET) & PrimeMask) == 0U) {
				PrimeClear = 1;
				break;
			}
		}
		if (!PrimeClear) break;
		Status = XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
					XUSBPS_EPRDY_OFFSET) & FlushMask;
		++A;
		if (Status == 0U) {
			Result = XST_SUCCESS;
			break;
		}
	}
done:
	if (FlushPolls != NULL) *FlushPolls = F;
	if (PrimePolls != NULL) *PrimePolls = P;
	if (ActivePolls != NULL) *ActivePolls = A;
	if (ActiveStatus != NULL) *ActiveStatus = Status;
	return Result;
}

static inline int XUsbPs_BoundedQuiesceEndpointWithLimit(
											XUsbPs *InstancePtr, u8 EpNum,
											u8 Direction, u32 PrimeMask,
											u32 FlushMask, u32 PollLimit,
											u32 *FlushPolls, u32 *PrimePolls)
{
	return XUsbPs_BoundedQuiesceEndpointWithStatusWithLimit(
		InstancePtr, EpNum, Direction, PrimeMask, FlushMask, PollLimit,
		FlushPolls, PrimePolls, NULL, NULL);
}

static inline int XUsbPs_BoundedQuiesceEndpoint(XUsbPs *InstancePtr, u8 EpNum,
							u8 Direction, u32 PrimeMask,
							u32 FlushMask)
{
	return XUsbPs_BoundedQuiesceEndpointWithLimit(InstancePtr, EpNum, Direction,
							      PrimeMask, FlushMask,
							      XUSBPS_BOUNDED_POLL_LIMIT,
							      NULL, NULL);
}

static inline int XUsbPs_BoundedQuiesceInEndpoint(XUsbPs *InstancePtr, u8 EpNum,
							  u32 PrimeMask, u32 FlushMask)
{
	return XUsbPs_BoundedQuiesceEndpoint(InstancePtr, EpNum,
						     XUSBPS_EP_DIRECTION_IN,
							     PrimeMask, FlushMask);
}

static inline int XUsbPs_BoundedQuiesceInEndpointWithLimit(
							  XUsbPs *InstancePtr, u8 EpNum,
							  u32 PrimeMask, u32 FlushMask,
							  u32 PollLimit, u32 *FlushPolls,
							  u32 *PrimePolls)
{
	return XUsbPs_BoundedQuiesceEndpointWithLimit(
		InstancePtr, EpNum, XUSBPS_EP_DIRECTION_IN, PrimeMask, FlushMask,
		PollLimit, FlushPolls, PrimePolls);
}

static inline int XUsbPs_BoundedQuiesceInEndpointWithStatusWithLimit(
											XUsbPs *InstancePtr, u8 EpNum,
											u32 PrimeMask, u32 FlushMask,
											u32 PollLimit, u32 *FlushPolls,
											u32 *PrimePolls, u32 *ActivePolls,
											u32 *ActiveStatus)
{
	return XUsbPs_BoundedQuiesceEndpointWithStatusWithLimit(
		InstancePtr, EpNum, XUSBPS_EP_DIRECTION_IN, PrimeMask, FlushMask,
		PollLimit, FlushPolls, PrimePolls, ActivePolls, ActiveStatus);
}

/* EPCOMPL is write-one-to-clear. Retire only the already-quiesced direction
 * before rebuilding its dTD ring, then verify the stale completion is gone. */
static inline int XUsbPs_BoundedClearEndpointCompletion(XUsbPs *InstancePtr,
								 u32 CompletionMask)
{
	if (InstancePtr == NULL || CompletionMask == 0U) return XST_FAILURE;
	XUsbPs_WriteReg(InstancePtr->Config.BaseAddress,
			XUSBPS_EPCOMPL_OFFSET, CompletionMask);
#if defined(__arm__) && !defined(G6_USB_NATIVE_TEST)
	__asm__ volatile("dsb sy" ::: "memory");
#else
	__asm__ volatile("" ::: "memory");
#endif
	return (XUsbPs_ReadReg(InstancePtr->Config.BaseAddress,
			       XUSBPS_EPCOMPL_OFFSET) & CompletionMask) == 0U ?
		XST_SUCCESS : XST_FAILURE;
}

/* Route every Chapter 9 EP0 reply through one status/error path.  The caller
 * owns the common EP0 stall and return after inspecting Error. */
#ifndef XUSBPS_BOUNDED_POLICY_NO_CH9
static inline int XUsbPs_Ch9QueueEp0Reply(XUsbPs *InstancePtr, u8 EpNum,
					   const u8 *BufferPtr, u32 BufferLen,
					   int *Status, int *Error)
{
	*Status = XUsbPs_EpBufferSend(InstancePtr, EpNum, BufferPtr, BufferLen);
	if (*Status != XST_SUCCESS) {
		XUsbPs_BoundedMarkEndpointFaulted(InstancePtr, EpNum);
		*Error = 1;
		*Status = XST_FAILURE;
	}
	return *Status;
}
#endif /* XUSBPS_BOUNDED_POLICY_NO_CH9 */

#endif /* EYEPQC_USB_BOUNDED_SDK_POLICY_H */
