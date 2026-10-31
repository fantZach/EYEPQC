/* Cross-language fixture: exercise the actual state implementation on Python-prepared files. */
#include "g6_sd_state.h"
#include "session.h"
#include <stdio.h>
#include <string.h>
#ifdef _WIN32
#include <io.h>
#define durable(f) _commit(_fileno(f))
#else
#include <unistd.h>
#define durable(f) fsync(fileno(f))
#endif

static const char *paths[2];
static int read_slot(unsigned slot, uint8_t out[80]) {
    FILE *file = fopen(paths[slot], "rb");
    if (!file) return 1;
    int bad = fread(out, 1, 80, file) != 80 || fgetc(file) != EOF || ferror(file);
    return fclose(file) || bad;
}
static int write_slot(unsigned slot, const uint8_t data[80]) {
    FILE *file = fopen(paths[slot], "r+b");
    if (!file) return 1;
    int bad = fwrite(data, 1, 80, file) != 80 || fflush(file) || durable(file);
    return fclose(file) || bad;
}
int main(int argc, char **argv) {
    uint8_t public_key[800], pin[32], additional[32] = {0}, output[64];
    struct eye_sd_state state;
    const struct eye_sd_ops ops = {read_slot, write_slot};
    if (argc != 5) return 2;
    paths[0] = argv[1]; paths[1] = argv[2];
    FILE *file = fopen(argv[3], "rb");
    if (!file) return 3;
    int bad = fread(public_key, 1, 800, file) != 800 || fgetc(file) != EOF || ferror(file);
    if (fclose(file) || bad || eye_sha256(pin, public_key, sizeof public_key)) return 4;
    if (eye_sd_state_open(&state, &ops, pin) ||
        eye_sd_state_random(&state, &ops, output, sizeof output, additional)) return 5;
    file = fopen(argv[4], "wb");
    if (!file) return 6;
    bad = fwrite(output, 1, sizeof output, file) != sizeof output || fflush(file);
    if (fclose(file) || bad) return 7;
    memset(output, 0, sizeof output);
    printf("SD_STATE_FILE_PASS generation=%llu\n", (unsigned long long)state.generation);
    eye_sd_state_wipe(&state);
    return 0;
}
