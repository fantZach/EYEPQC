/* Synthetic offline wire fixture; activation deliberately mocked, not hardware. */
#include <stdio.h>
#include <stdlib.h>
#include "g6_dev_bootstrap.h"
static int activate(const uint8_t p[32], const uint8_t k[1632], const uint8_t s[32])
{ (void)p; (void)k; (void)s; return 0; }
static int digit(int c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
int main(void) {
    struct eye_bootstrap state = {0};
    char line[2075]; uint8_t payload[1036], response[EYE_BOOT_ACK];
    unsigned tick = 0;
    while (fgets(line, sizeof line, stdin)) {
        size_t n = strcspn(line, "\r\n");
        if (!n || n > 2072 || n % 2) return 2;
        for (size_t i = 0; i < n; i += 2) {
            int high = digit(line[i]), low = digit(line[i + 1]);
            if (high < 0 || low < 0) return 2;
            payload[i / 2] = (uint8_t)(high * 16 + low);
        }
        (void)eye_boot_process(&state, payload, (unsigned)n / 2, tick++, 1, activate);
        eye_boot_reply(&state, response);
        eye_g6_control_wipe(payload, sizeof payload);
        for (unsigned i = 0; i < sizeof response; ++i) printf("%02x", response[i]);
        putchar('\n'); fflush(stdout);
    }
    eye_boot_fault(&state);
    return ferror(stdin) ? 1 : 0;
}
