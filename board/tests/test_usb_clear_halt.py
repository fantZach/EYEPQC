"""Execute generated CH9, not a copied CLEAR_FEATURE implementation."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sim.tb import test_usb_bounded_sdk as sdk_test


class ClearHaltTests(unittest.TestCase):
    def test_generated_ch9_resets_only_valid_endpoint_direction(self):
        source = sdk_test.INTR_MOCK_C.read_text()
        old = '''void XUsbPs_SetBits(XUsbPs *instance, u32 offset, u32 mask)
{ (void)instance; (void)offset; (void)mask; }
void XUsbPs_ClrBits(XUsbPs *instance, u32 offset, u32 mask)
{ (void)instance; (void)offset; (void)mask; }'''
        new = '''static u32 observed_set, observed_clear, observed_offset;
void XUsbPs_SetBits(XUsbPs *instance, u32 offset, u32 mask)
{ (void)instance; observed_offset = offset; observed_set |= mask; }
void XUsbPs_ClrBits(XUsbPs *instance, u32 offset, u32 mask)
{ (void)instance; observed_offset = offset; observed_clear |= mask; }'''
        self.assertEqual(source.count(old), 1)
        self.assertEqual(source.count('int main(void)'), 1)
        source = source.replace(old, new).replace('int main(void)', 'int legacy_mock_main(void)')
        source += r'''
int main(void) {
    const unsigned endpoints[] = {1, 0x81, 0x82, 0, 0x80, 2, 3, 0x83, 0x11, 0x101, 0xff81};
    for (unsigned i = 0; i < sizeof endpoints / sizeof endpoints[0] + 5; ++i) {
        fixture_reset(); observed_set = observed_clear = observed_offset = 0;
        XUsbPs_Local local = {0}; usb.UserDataPtr = &local;
        XUsbPs_SetupData request = {0};
        request.bmRequestType = XUSBPS_STATUS_ENDPOINT;
        request.bRequest = XUSBPS_REQ_CLEAR_FEATURE;
        request.wValue = XUSBPS_ENDPOINT_HALT;
        request.wIndex = i < sizeof endpoints / sizeof endpoints[0] ? endpoints[i] : 0x81;
        if (i == sizeof endpoints / sizeof endpoints[0]) request.wLength = 1;
        if (i == sizeof endpoints / sizeof endpoints[0] + 1) request.wValue = 1;
        if (i == sizeof endpoints / sizeof endpoints[0] + 2) request.bmRequestType |= 0x80;
        if (i == sizeof endpoints / sizeof endpoints[0] + 3) usb.DeviceConfig.NumEndpoints = 1;
        if (i == sizeof endpoints / sizeof endpoints[0] + 4) request.bmRequestType = XUSBPS_STATUS_INTERFACE;
        u32 before_in = XUsbPs_Ch9ClearHaltInCount, before_out = XUsbPs_Ch9ClearHaltOutCount;
        u32 before_last = XUsbPs_Ch9ClearHaltLastEndpoint;
        int result = XUsbPs_Ch9HandleSetupPacket(&usb, &request);
        if (i < 3) {
            u32 reset = request.wIndex & 0x80 ? XUSBPS_EPCR_TXR_MASK : XUSBPS_EPCR_RXR_MASK;
            u32 stall = request.wIndex & 0x80 ? XUSBPS_EPCR_TXS_MASK : XUSBPS_EPCR_RXS_MASK;
            assert(result == XST_SUCCESS && !stall_count && send_count == 1);
            assert(observed_offset == XUSBPS_EPCRn_OFFSET(request.wIndex & 15));
            assert(observed_set == reset && observed_clear == stall);
            assert(XUsbPs_Ch9ClearHaltInCount == before_in + !!(request.wIndex & 0x80));
            assert(XUsbPs_Ch9ClearHaltOutCount == before_out + !(request.wIndex & 0x80));
            assert(XUsbPs_Ch9ClearHaltLastEndpoint == request.wIndex);
        } else {
            assert(result == XST_FAILURE && stall_count == 1 && !send_count);
            assert(!observed_set && !observed_clear && !observed_offset);
            assert(XUsbPs_Ch9ClearHaltInCount == before_in && XUsbPs_Ch9ClearHaltOutCount == before_out);
            assert(XUsbPs_Ch9ClearHaltLastEndpoint == before_last);
        }
    }
    fixture_reset(); fail_send = 1;
    XUsbPs_Local local = {0}; usb.UserDataPtr = &local;
    XUsbPs_SetupData request = {0};
    request.bmRequestType = XUSBPS_STATUS_ENDPOINT;
    request.bRequest = XUSBPS_REQ_CLEAR_FEATURE;
    request.wValue = XUSBPS_ENDPOINT_HALT; request.wIndex = 0x81;
    assert(XUsbPs_Ch9HandleSetupPacket(&usb, &request) == XST_FAILURE);
    assert(stall_count && send_count == 1 && XUsbPs_BoundedEndpointIsFaulted(&usb, 0));
    puts("GENERATED_CLEAR_HALT_RESET_VALIDATION_PASS"); return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='eyepqc-clear-halt-') as directory:
            fixture = Path(directory) / 'clear_halt.c'
            fixture.write_text(source)
            with mock.patch.object(sdk_test, 'INTR_MOCK_C', fixture), mock.patch.object(
                    sdk_test, 'DRIVER_ROOT', Path('D:/AmdDesignTools/2026.1/Vitis/data/embeddedsw/'
                                                 'XilinxProcessorIPLib/drivers/usbps_v2_11')), mock.patch.object(
                    sdk_test, 'NATIVE_GCC', 'C:/msys64/ucrt64/bin/gcc.exe'):
                sdk_test.test_generated_intr_and_cdc_class_execute_with_host_stubs()


if __name__ == '__main__':
    unittest.main()
