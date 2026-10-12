/* G4: OV5640 JPEG -> DDR -> plaintext v1 USB CDC video records. */
#include "xil_printf.h"
#ifdef SDT
#include "xiltimer.h"
#else
#include "xtime_l.h"
#endif
#include <stdint.h>
#include <string.h>

#define PAYLOAD 1400U
#define CAMERA_CFG ((1U << 25) | (1000U << 9) | (12U << 3) | 4U | 2U)

int g3_usb_init(unsigned camera_cfg);
int g3_usb_capture(const uint8_t **data, unsigned *size);
int g3_usb_flush(void);
int g3_usb_resume(void);
void g3_usb_zeroize(void);
int g3_usb_encrypt(const uint8_t *plain, unsigned size, const uint8_t aad[40],
                   const uint8_t key[16], uint32_t epoch, uint64_t sequence,
                   const uint8_t **sealed);
int usb_cdc_init(void);
int usb_cdc_ready(void);
int usb_cdc_send(uint8_t *data, uint32_t size);
uint32_t usb_cdc_test_epoch(void);

static uint8_t record[3 + 40 + PAYLOAD + 16] __attribute__((aligned(64)));
#ifdef G5_USB
static const uint8_t g5_test_key[16] = {
    0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
    0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff
}; // ponytail: public test key only; G6 uses a derived key.
#endif
static void be16(uint8_t *p, uint32_t n) { p[0] = n >> 8; p[1] = n; }
static void be32(uint8_t *p, uint32_t n) { p[0] = n >> 24; p[1] = n >> 16; p[2] = n >> 8; p[3] = n; }
static void be64(uint8_t *p, uint64_t n) { be32(p, n >> 32); be32(p + 4, n); }

static int send_frame(const uint8_t *jpeg, unsigned size, uint32_t frame_id,
                      uint64_t *sequence)
{
    unsigned count = (size + PAYLOAD - 1U) / PAYLOAD;
    XTime ticks;
    XTime_GetTime(&ticks);
    uint64_t timestamp = (uint64_t)ticks * 1000000U / COUNTS_PER_SECOND;
    for (unsigned index = 0, offset = 0; index < count; ++index) {
        unsigned length = size - offset < PAYLOAD ? size - offset : PAYLOAD;
        if (*sequence == UINT64_MAX) return 2;
        uint64_t packet_sequence = (*sequence)++;
        memset(record, 0, 43);
        record[0] = 2;
#ifdef G5_USB
        be16(record + 1, 40 + length + 16);
        record[4] = 1;
#else
        be16(record + 1, 40 + length);
#endif
        record[3] = 1;
        be16(record + 5, 40);
        be32(record + 11, frame_id);
        be16(record + 15, index);
        be16(record + 17, count);
        be32(record + 19, size);
        be16(record + 23, length);
        be64(record + 27, timestamp);
        be64(record + 35, packet_sequence);
#ifdef G5_USB
        const uint8_t *sealed;
        if (g3_usb_encrypt(jpeg + offset, length, record + 3,
                           g5_test_key, usb_cdc_test_epoch(), packet_sequence,
                           &sealed)) return 3;
        memcpy(record + 43, sealed, length + 16);
        if (usb_cdc_send(record, 43 + length + 16)) return 1;
#else
        memcpy(record + 43, jpeg + offset, length);
        if (usb_cdc_send(record, 43 + length)) return 1;
#endif
        offset += length;
    }
    return 0;
}

int main(void)
{
    int status = g3_usb_init(CAMERA_CFG);
    if (!status) status = usb_cdc_init();
    if (status) {
        xil_printf("G4_INIT_FAIL %d\r\n", status);
        for (;;) {}
    }
    xil_printf("G4_READY\r\n");
    uint32_t frame_id = 0;
    uint64_t sequence = 0;
    int started = 0;
    unsigned dropped = 0, consecutive_errors = 0;
    for (;;) {
        if (!usb_cdc_ready()) { started = 0; continue; }
        if (!started) {
            if (g3_usb_flush()) {
                xil_printf("G4_FLUSH_FAIL\r\n");
                for (;;) {}
            }
            started = 1;
        }
        const uint8_t *jpeg;
        unsigned size;
        status = g3_usb_capture(&jpeg, &size);
        if (status) {
            ++dropped;
            xil_printf("G4_CAPTURE_DROP status=%d total=%u\r\n", status, dropped);
            if (++consecutive_errors > 10 || g3_usb_flush()) {
                xil_printf("G4_CAPTURE_FAIL %d\r\n", status);
                for (;;) {}
            }
            continue;
        }
        consecutive_errors = 0;
        int sent = send_frame(jpeg, size, frame_id, &sequence);
#ifdef G5_USB
        g3_usb_zeroize();
#endif
        if (g3_usb_resume()) {
            xil_printf("G4_RESUME_FAIL\r\n");
            for (;;) {}
        }
        if (!sent) {
            ++frame_id;
            if (frame_id % 100U == 0) xil_printf("G4_LIVE frame=%u bytes=%u dropped=%u\r\n", frame_id, size, dropped);
        }
        else started = 0;
    }
}
