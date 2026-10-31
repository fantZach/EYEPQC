/* Native FatFS/SD-host adapter exercise. No actual SD or keys are accessed. */
#include "g6_sd_identity.h"
#include "session.h"
#include "ff.h"
#include "xtime_l.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint8_t files[3][1632];
static unsigned lengths[3] = {1632,80,80};
static int mode, ticks, reads, writes, syncs;
static void init_files(void) {
    memset(files, 0, sizeof files);
    memcpy(files[1], "EYERNG01", 8);
    memset(files[1] + 16, 0x61, 32);
    assert(!eye_sha256(files[1] + 48, files[1], 48));
    memcpy(files[2], files[1], 80);
    mode = ticks = reads = writes = syncs = 0;
    lengths[0] = 1632; lengths[1] = lengths[2] = 80;
}
int f_mount(FATFS *fs, const char *name, int now) {
    (void)name; (void)now;
    return fs && mode == 1;
}
int f_open(FIL *f, const char *name, int flags) {
    (void)flags;
    f->index = strstr(name,"EYEKEY") ? 0 : strstr(name,"EYERNG0") ? 1 : 2;
    f->size = lengths[f->index];
    return mode == 2;
}
int f_read(FIL *f, void *p, unsigned n, UINT *got) {
    ++reads;
    memcpy(p, files[f->index], n);
    *got = mode == 3 ? n - 1U : n;
    if (mode == 10 && writes) ((uint8_t *)p)[16] ^= 1;
    return 0;
}
int f_write(FIL *f, const void *p, unsigned n, UINT *got) {
    ++writes;
    memcpy(files[f->index], p, n);
    *got = n;
    return mode == 5;
}
int f_close(FIL *f) { (void)f; return mode == 4; }
int f_sync(FIL *f) { (void)f; ++syncs; return mode == 6; }
void XTime_GetTime(XTime *out) { *out = (XTime)ticks++; }
uint32_t mock_sd_read(void) {
    if (mode == 7) return 0x100001; /* Command inhibit. */
    if (mode == 8) return 0x100004; /* Data active. */
    if (mode == 9) return 0;        /* DAT0 busy. */
    return 0x100000;
}
static int zero(const uint8_t *p, unsigned n) {
    for (unsigned i=0;i<n;++i) if (p[i]) return 0;
    return 1;
}
int main(void) {
    uint8_t key[1632], output[64], additional[32] = {0};
    init_files();
    assert(!g6_sd_identity_init(key));
    assert(writes == 1 && syncs == 1 && reads == 4);
    assert(!g6_sd_identity_random(output, 64, additional));
    assert(writes == 2 && syncs == 2);
    g6_sd_identity_shutdown();
    assert(g6_sd_identity_random(output, 64, additional));
    assert(zero(output, 64));
    for (int failure=1;failure<=10;++failure) {
        init_files(); mode=failure;
        memset(key, 0x11, sizeof key);
        assert(g6_sd_identity_init(key));
        assert(zero(key, sizeof key));
        assert(ticks <= 12); /* Busy register wait is bounded to one mock second. */
    }
    init_files(); lengths[0] = 1631;
    assert(g6_sd_identity_init(key) && zero(key, sizeof key));
    init_files(); lengths[1] = 79;
    assert(g6_sd_identity_init(key) && zero(key, sizeof key));
    puts("G6_SD_ADAPTER_PASS failures=10 sizes=2 bounded_idle=PASS");
    return 0;
}
