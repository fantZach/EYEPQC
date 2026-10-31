#include "g6_sd_identity.h"
#include "g6_sd_state.h"
#include "ff.h"
#include "tinycrypt/sha256.h"
#include "xparameters.h"
#include "xsdps_hw.h"
#include "xtime_l.h"
#include <string.h>
static FATFS filesystem;
static struct eye_sd_state state;
static const char *const names[2] = {"0:/EYERNG0.BIN", "0:/EYERNG1.BIN"};
static void wipe(void *p, unsigned n) {
    volatile uint8_t *v = p;
    while (n--) *v++ = 0;
}
/* AMD exposes DAT[3:0] as a group; its least significant bit is DAT0. */
#define SD_DAT0_HIGH (XSDPS_PSR_DAT30_SG_LVL_MASK & (0U - XSDPS_PSR_DAT30_SG_LVL_MASK))
static int wait_sd_idle(void) {
    XTime started, now;
    XTime_GetTime(&started);
    do {
        uint32_t value = XSdPs_ReadReg(XPAR_PS7_SD_0_BASEADDR, XSDPS_PRES_STATE_OFFSET);
        if (!(value & (XSDPS_PSR_INHIBIT_CMD_MASK | XSDPS_PSR_INHIBIT_DAT_MASK |
                       XSDPS_PSR_DAT_ACTIVE_MASK)) && (value & SD_DAT0_HIGH)) return 0;
        XTime_GetTime(&now);
    } while (now - started < COUNTS_PER_SECOND);
    return 1;
}
static int read_exact(const char *name, uint8_t *out, unsigned length) {
    FIL file;
    UINT count = 0;
    if (f_open(&file, name, FA_READ) != FR_OK) return 1;
    int bad = f_size(&file) != length;
    if (!bad) bad = f_read(&file, out, length, &count) != FR_OK || count != length;
    if (f_close(&file) != FR_OK) bad = 1;
    wipe(&file, sizeof file);
    return bad;
}
static int read_slot(unsigned slot, uint8_t out[80]) {
    return slot > 1U || read_exact(names[slot], out, 80);
}
static int write_slot(unsigned slot, const uint8_t data[80]) {
    FIL file;
    UINT count = 0;
    if (slot > 1U || f_open(&file, names[slot], FA_WRITE) != FR_OK) return 1;
    int bad = f_size(&file) != 80U;
    if (!bad) bad = f_write(&file, data, 80, &count) != FR_OK || count != 80U;
    if (!bad) bad = f_sync(&file) != FR_OK;
    if (f_close(&file) != FR_OK) bad = 1;
    wipe(&file, sizeof file);
    /* AMD CTRL_SYNC is a no-op. Observe host idle/DAT0 released as well;
     * this is not a guarantee of SD flash persistence after power loss. */
    if (!bad) bad = wait_sd_idle();
    return bad;
}
static const struct eye_sd_ops ops = {read_slot, write_slot};
void g6_sd_identity_shutdown(void) {
    eye_sd_state_wipe(&state);
    (void)f_mount(NULL, "0:/", 0);
    wipe(&filesystem, sizeof filesystem);
}
int g6_sd_identity_init(uint8_t private_key[1632]) {
    uint8_t discard[32] = {0}, additional[32] = {0};
    uint8_t pin[32] = {0};
    struct tc_sha256_state_struct ctx;
    int bad = f_mount(&filesystem, "0:/", 1) != FR_OK ||
              read_exact("0:/EYEKEY.BIN", private_key, 1632);
    if (!bad) bad = !(tc_sha256_init(&ctx) &&
                       tc_sha256_update(&ctx, private_key + 768, 800) &&
                       tc_sha256_final(pin, &ctx));
    if (!bad) bad = eye_sd_state_open(&state, &ops, pin);
    /* Reserve a boot transition before advertising readiness. */
    if (!bad) bad = eye_sd_state_random(&state, &ops, discard, 32, additional);
    wipe(discard, sizeof discard);
    wipe(&ctx, sizeof ctx);
    if (bad) {
        wipe(private_key, 1632);
        g6_sd_identity_shutdown();
    }
    return bad;
}
int g6_sd_identity_random(uint8_t *out, size_t length, const uint8_t additional[32]) {
    return eye_sd_state_random(&state, &ops, out, length, additional);
}
