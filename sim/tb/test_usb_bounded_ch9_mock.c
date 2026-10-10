#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "xusbps_ch9.c"

static int send_status;
static int receive_status;
static unsigned send_count;
static unsigned stall_count;
static unsigned reconfigure_count;
static unsigned unstall_count;
static u32 epcompl_register;
static u32 epflush_register;
static u32 epprime_register;
static unsigned epflush_reads;
static int flush_stuck;
static int ep_disabled;
static u32 endpoint_fault_mask;
static const u8 *last_send_buffer;
static XUsbPs_dTD transfer_ring[2];
static XUsbPs_dQH queue_head;

int XUsbPs_EpBufferSend(XUsbPs *InstancePtr, u8 EpNum, const u8 *BufferPtr, u32 BufferLen)
{
	assert(EpNum == 0U);
	(void)BufferLen;
	assert((epcompl_register & (1U << XUSBPS_EPFLUSH_TX_SHIFT)) == 0U);
	++send_count;
	last_send_buffer = BufferPtr;
	if (send_status == XST_SUCCESS) {
		XUsbPs_EpIn *ep = &InstancePtr->DeviceConfig.Ep[0].In;
		ep->dTDHead->token = XUSBPS_dTDTOKEN_ACTIVE_MASK;
		ep->dTDHead->active = 1U;
		ep->dTDHead = XUsbPs_dTDGetNLP(ep->dTDHead);
		epcompl_register |= (1U << XUSBPS_EPFLUSH_TX_SHIFT);
	}
	return send_status;
}

void XUsbPs_EpStall(XUsbPs *InstancePtr, u8 EpNum, u8 Direction)
{
	(void)InstancePtr;
	assert(EpNum == 0U);
	assert(Direction == (XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT));
	++stall_count;
}

void XUsbPs_BoundedMarkEndpointFaulted(XUsbPs *InstancePtr, u8 EpNum)
{
	(void)InstancePtr;
	endpoint_fault_mask |= (1U << EpNum);
}

int XUsbPs_BoundedEndpointIsFaulted(XUsbPs *InstancePtr, u8 EpNum)
{
	(void)InstancePtr;
	return (endpoint_fault_mask & (1U << EpNum)) != 0U;
}

void XUsbPs_BoundedClearEndpointFaults(XUsbPs *InstancePtr)
{
	(void)InstancePtr;
	endpoint_fault_mask = 0U;
}

void XUsbPs_BoundedClearEndpointFault(XUsbPs *InstancePtr, u8 EpNum)
{ (void)InstancePtr; endpoint_fault_mask &= ~(1U << EpNum); }

int XUsbPs_EpBufferReceive(XUsbPs *InstancePtr, u8 EpNum, u8 **BufferPtr,
			   u32 *BufferLen, u32 *Handler)
{
	(void)InstancePtr; (void)EpNum; (void)BufferPtr; (void)BufferLen; (void)Handler;
	return receive_status;
}

void XUsbPs_EpBufferRelease(u32 Handler) { (void)Handler; }
void XUsbPs_SetDeviceAddress(XUsbPs *InstancePtr, u32 Address)
{ (void)InstancePtr; (void)Address; }
u32 XUsbPs_ReadReg(uintptr_t Base, u32 Offset)
{
	(void)Base;
	if (Offset == XUSBPS_EPPRIME_OFFSET) return epprime_register;
	if (Offset == XUSBPS_EPFLUSH_OFFSET) {
		++epflush_reads;
		if (!flush_stuck && epflush_reads > 1U) epflush_register = 0U;
		return epflush_register;
	}
	if (Offset == XUSBPS_EPCOMPL_OFFSET) return epcompl_register;
	return 0U;
}
void XUsbPs_WriteReg(uintptr_t Base, u32 Offset, u32 Value)
{
	(void)Base;
	if (Offset == XUSBPS_EPCOMPL_OFFSET) epcompl_register &= ~Value;
}
void XUsbPs_ClrBits(XUsbPs *InstancePtr, u32 Offset, u32 Mask)
{ (void)InstancePtr; (void)Offset; (void)Mask; }
void XUsbPs_SetBits(XUsbPs *InstancePtr, u32 Offset, u32 Mask)
{ (void)InstancePtr; (void)Offset; (void)Mask; }
int XUsbPs_EpPrime(XUsbPs *InstancePtr, u8 EpNum, u8 Direction)
{ (void)InstancePtr; (void)EpNum; (void)Direction; return XST_SUCCESS; }
void XUsbPs_MockEpFlush(XUsbPs *InstancePtr, u8 EpNum, u8 Direction)
{
	(void)InstancePtr; assert(EpNum == 0U); assert(Direction == XUSBPS_EP_DIRECTION_IN);
	epflush_register = 1U << (EpNum + XUSBPS_EPFLUSH_TX_SHIFT);
	epflush_reads = 0U;
}
void XUsbPs_MockEpDisable(XUsbPs *InstancePtr, u8 EpNum, u8 Direction)
{ (void)InstancePtr; assert(EpNum == 0U); assert(Direction == XUSBPS_EP_DIRECTION_IN); ep_disabled = 1; }
void XUsbPs_MockEpEnable(XUsbPs *InstancePtr, u8 EpNum, u8 Direction)
{ (void)InstancePtr; assert(EpNum == 0U); assert(Direction == XUSBPS_EP_DIRECTION_IN); ep_disabled = 0; }
void XUsbPs_MockEpUnStall(XUsbPs *InstancePtr, u8 EpNum, u8 Direction)
{ (void)InstancePtr; assert(EpNum == 0U); assert(Direction == (XUSBPS_EP_DIRECTION_IN | XUSBPS_EP_DIRECTION_OUT)); ++unstall_count; }
int XUsbPs_ReconfigureEp(XUsbPs *InstancePtr, XUsbPs_DeviceConfig *Config,
			 int EpNum, unsigned short Direction, int DirectionChanged)
{
	XUsbPs_EpIn *ep;
	unsigned i;
	(void)Config; (void)DirectionChanged;
	assert(EpNum == 0 && Direction == XUSBPS_EP_DIRECTION_IN);
	assert(ep_disabled);
	++reconfigure_count;
	ep = &InstancePtr->DeviceConfig.Ep[0].In;
	for (i = 0U; i < InstancePtr->DeviceConfig.EpCfg[0].In.NumBufs; ++i) {
		ep->dTDs[i].next = &ep->dTDs[(i + 1U) % 2U];
		ep->dTDs[i].token = 0U;
		ep->dTDs[i].active = 0U;
	}
	ep->dTDHead = ep->dTDs;
	ep->dTDTail = ep->dTDs;
	return XST_SUCCESS;
}
void Xil_DCacheInvalidateRange(uintptr_t Address, u32 Length)
{ (void)Address; (void)Length; }
int usleep(unsigned int Usec) { (void)Usec; return 0; }

u32 XUsbPs_Ch9SetupDevDescReply(u8 *Buffer, u32 Length)
{ (void)Buffer; (void)Length; return 0U; }
u32 XUsbPs_Ch9SetupCfgDescReply(u8 *Buffer, u32 Length)
{ (void)Buffer; (void)Length; return 0U; }
u32 XUsbPs_Ch9SetupStrDescReply(u8 *Buffer, u32 Length, u8 Index)
{ (void)Buffer; (void)Length; (void)Index; return 0U; }
u32 XUsbPs_Ch9SetupHidDescReply(u8 *Buffer, u32 Length)
{ (void)Buffer; (void)Length; return 0U; }
u32 XUsbPs_Ch9SetupReportDescReply(u8 *Buffer, u32 Length)
{ (void)Buffer; (void)Length; return 0U; }
void XUsbPs_SetConfiguration(XUsbPs *InstancePtr, int ConfigIdx)
{ (void)InstancePtr; (void)ConfigIdx; }
void XUsbPs_SetConfigurationApp(XUsbPs *InstancePtr, XUsbPs_SetupData *SetupData)
{ (void)InstancePtr; (void)SetupData; }
void XUsbPs_SetInterfaceHandler(XUsbPs *InstancePtr, XUsbPs_SetupData *SetupData)
{ (void)InstancePtr; (void)SetupData; }
void XUsbPs_ClassReq(XUsbPs *InstancePtr, XUsbPs_SetupData *SetupData)
{ (void)InstancePtr; (void)SetupData; }
static void reset_observations(void)
{
	send_status = XST_SUCCESS;
	receive_status = XST_SUCCESS;
	send_count = stall_count = 0U;
	reconfigure_count = unstall_count = 0U;
	epcompl_register = epflush_register = epflush_reads = 0U;
	epprime_register = 0U;
	flush_stuck = 0;
	ep_disabled = 0;
	last_send_buffer = NULL;
}

int main(void)
{
	XUsbPs usb = {0};
	XUsbPs_Local local = {0};
	XUsbPs_SetupData request = {0};
	u8 reply_snapshot[16];
	const u8 *reply_buffer;
	usb.UserDataPtr = &local;
	usb.DeviceConfig.EpCfg[0].In.NumBufs = 2U;
	usb.DeviceConfig.Ep[0].In.dTDs = transfer_ring;
	usb.DeviceConfig.Ep[0].In.dQH = &queue_head;
	usb.DeviceConfig.Ep[0].In.dTDHead = &transfer_ring[0];
	usb.DeviceConfig.Ep[0].In.dTDTail = &transfer_ring[0];
	transfer_ring[0].next = &transfer_ring[1];
	transfer_ring[1].next = &transfer_ring[0];

	endpoint_fault_mask = 0U;
	reset_observations();
	request.bRequest = XUSBPS_REQ_GET_STATUS;
	request.bmRequestType = XUSBPS_STATUS_DEVICE;
	request.wLength = 2U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 1U && stall_count == 0U);
	assert(last_send_buffer != NULL);
	reply_buffer = last_send_buffer;
	memcpy(reply_snapshot, reply_buffer, sizeof reply_snapshot);
	XUsbPs_BoundedMarkEndpointFaulted(&usb, 1U);

	/* A legal new SETUP aborts the prior IN transfer. The handler must flush,
	 * clear the stale completion before queueing, rebuild, then send the reply. */
	request.bRequest = XUSBPS_REQ_GET_STATUS;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 2U && stall_count == 0U);
	assert(!XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 1U));
	assert(reconfigure_count == 1U && unstall_count == 1U);
	assert(epcompl_register & (1U << XUSBPS_EPFLUSH_TX_SHIFT));
	assert(XUsbPs_Ch9OwnershipDiagnostics.last_request == XUSBPS_REQ_GET_STATUS);
	assert(XUsbPs_Ch9OwnershipDiagnostics.last_result == XST_SUCCESS);

	/* PRIME stuck is a bounded fail-closed path; it must not touch the static
	 * reply or rebuild while the controller may still own the endpoint. */
	reply_buffer = last_send_buffer;
	memcpy(reply_snapshot, reply_buffer, sizeof reply_snapshot);
	epprime_register = 1U << XUSBPS_EPFLUSH_TX_SHIFT;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
	assert(send_count == 2U && stall_count == 1U);
	assert(reconfigure_count == 1U);
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_Ch9OwnershipDiagnostics.last_reason & XUSBPS_CH9_OWNERSHIP_FLUSH_FAILED);
	assert(memcmp(reply_snapshot, reply_buffer, sizeof reply_snapshot) == 0);
	epprime_register = 0U;
	flush_stuck = 0;
	epflush_register = 0U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 3U && stall_count == 1U);
	assert(!XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 1U));
	assert(reconfigure_count == 2U && unstall_count == 2U);

	/* A flush timeout is fail-closed and cannot overwrite the published reply. */
	reply_buffer = last_send_buffer;
	memcpy(reply_snapshot, reply_buffer, sizeof reply_snapshot);
	flush_stuck = 1;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
	assert(send_count == 3U && stall_count == 2U);
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_Ch9OwnershipDiagnostics.last_result == XST_FAILURE);
	assert(XUsbPs_Ch9OwnershipDiagnostics.last_reason & XUSBPS_CH9_OWNERSHIP_FLUSH_FAILED);
	assert(memcmp(reply_snapshot, reply_buffer, sizeof reply_snapshot) == 0);

	/* A later SETUP can recover only after a successful bounded cancel/rebuild.
	 * The old EPCOMPL is cleared before send; the new send's bit remains set. */
	flush_stuck = 0;
	epflush_register = 0U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 4U && stall_count == 2U);
	assert(!XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 1U));
	assert(reconfigure_count == 3U && unstall_count == 3U);
	assert(epcompl_register & (1U << XUSBPS_EPFLUSH_TX_SHIFT));

	reset_observations();
	receive_status = XST_FAILURE;
	request.bRequest = XUSBPS_REQ_SET_SEL;
	request.wLength = 6U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
	assert(send_count == 0U && stall_count == 1U);

	/* Simulate a queue refusal after EpBufferSend. A later valid SETUP must
	 * recover only through the bounded cancel/rebuild path. */
	transfer_ring[0].active = transfer_ring[1].active = 0U;
	usb.DeviceConfig.Ep[0].In.dTDTail = usb.DeviceConfig.Ep[0].In.dTDHead;
	send_count = stall_count = 0U;
	last_send_buffer = NULL;
	receive_status = XST_SUCCESS;
	send_status = XST_USB_NO_DESC_AVAILABLE;
	request.bRequest = XUSBPS_REQ_SET_ADDRESS;
	request.wValue = 8U;
	request.wLength = 0U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
	assert(send_count == 1U && stall_count == 1U);
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));

	send_count = stall_count = 0U;
	last_send_buffer = NULL;
	request.bRequest = XUSBPS_REQ_GET_STATUS;
	request.bmRequestType = XUSBPS_STATUS_DEVICE;
	request.wLength = 2U;
	send_status = XST_SUCCESS;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 1U && stall_count == 0U);
	assert(!XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 1U));

	/* A corrupt queue-head pointer is an unsafe ring: fail before any static
	 * reply write or queue rebuild, then recover after the pointer is restored. */
	reply_buffer = last_send_buffer;
	memcpy(reply_snapshot, reply_buffer, sizeof reply_snapshot);
	usb.DeviceConfig.Ep[0].In.dQH = NULL;
	send_count = stall_count = 0U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
	assert(send_count == 0U && stall_count == 1U);
	assert(reconfigure_count == 2U);
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_Ch9OwnershipDiagnostics.last_reason & XUSBPS_CH9_OWNERSHIP_BAD_RING);
	assert(memcmp(reply_snapshot, reply_buffer, sizeof reply_snapshot) == 0);
	usb.DeviceConfig.Ep[0].In.dQH = &queue_head;
	send_count = stall_count = 0U;
	assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_SUCCESS);
	assert(send_count == 1U && stall_count == 0U);
	assert(reconfigure_count == 3U);
	assert(!XUsbPs_BoundedEndpointIsFaulted(&usb, 0U));
	assert(XUsbPs_BoundedEndpointIsFaulted(&usb, 1U));

	puts("generated Chapter 9 host mock: PASS");
	return 0;
}
