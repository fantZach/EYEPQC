#include "mlkem/mlkem_native.h"
#include "keccak_sponge_x4.h"
#include "keccak_sponge_x4_hostmock.h"
#include "mlkem_fips202_backend.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int read_exact(const char *path, uint8_t *dst, size_t length)
{
    FILE *f = fopen(path, "rb");
    int ok;
    if (f == NULL) return 0;
    ok = fread(dst, 1, length, f) == length && fgetc(f) == EOF;
    fclose(f);
    return ok;
}

static int write_exact(const char *path, const uint8_t *src, size_t length)
{
    FILE *f = fopen(path, "wb");
    int ok, close_ok;
    if (f == NULL) return 0;
    ok = fwrite(src, 1, length, f) == length;
    close_ok = fclose(f) == 0;
    return ok && close_ok;
}

int main(int argc, char **argv)
{
    uint8_t input[MLKEM512_SECRETKEYBYTES + MLKEM512_PUBLICKEYBYTES + 64];
    uint8_t expected[MLKEM512_SECRETKEYBYTES + MLKEM512_PUBLICKEYBYTES + 64];
    uint8_t output[MLKEM512_SECRETKEYBYTES + MLKEM512_PUBLICKEYBYTES + 64];
    size_t input_len, expected_len, output_len;
    int rc;
    int timeout_path;

    if (argc != 6) return 2;
    if (strcmp(argv[2], "hardware_mock") == 0) timeout_path=0;
    else if (strcmp(argv[2], "timeout_fallback") == 0) timeout_path=1;
    else return 11;
    if (strcmp(argv[1], "keygen") == 0) {
        input_len=64; expected_len=MLKEM512_PUBLICKEYBYTES+MLKEM512_SECRETKEYBYTES;
        output_len=expected_len;
    } else if (strcmp(argv[1], "encaps") == 0) {
        input_len=MLKEM512_PUBLICKEYBYTES+MLKEM_SYMBYTES;
        expected_len=MLKEM512_CIPHERTEXTBYTES+MLKEM_BYTES;
        output_len=expected_len;
    } else if (strcmp(argv[1], "decaps") == 0) {
        input_len=MLKEM512_SECRETKEYBYTES+MLKEM512_CIPHERTEXTBYTES;
        expected_len=MLKEM_BYTES; output_len=expected_len;
    } else return 3;

    memset(input,0,sizeof input); memset(expected,0,sizeof expected);
    memset(output,0,sizeof output);
    if (!read_exact(argv[3],input,input_len) ||
        !read_exact(argv[4],expected,expected_len)) return 4;

    {
        keccak_accel_io io;
        sx4_hostmock_reset(KECCAK_SX4_ID_VALUE,KECCAK_SX4_VERSION_VALUE);
        io.opaque=sx4_hostmock_opaque();
        io.read32=sx4_hostmock_read32;
        io.write32=sx4_hostmock_write32;
        io.activation_cookie=KECCAK_ACCEL_EXPERIMENTAL_ENABLE;
        if (!keccak_sponge_x4_configure(&io,32)) return 7;
        (void)mlkem_fips202_backend_configure(NULL,0);
        if (timeout_path) sx4_hostmock_set_failure(2,1);
        keccak_sponge_x4_reset_stats();
    }
    if (strcmp(argv[1], "keygen") == 0) {
        rc=eye_mlkem_keypair_derand(output,
            output+MLKEM512_PUBLICKEYBYTES,input);
    } else if (strcmp(argv[1], "encaps") == 0) {
        rc=eye_mlkem_enc_derand(output,output+MLKEM512_CIPHERTEXTBYTES,
            input,input+MLKEM512_PUBLICKEYBYTES);
    } else {
        rc=eye_mlkem_dec(output,input+MLKEM512_SECRETKEYBYTES,input);
    }
    if (rc != 0 || memcmp(output,expected,output_len) != 0) return 5;
    {
        keccak_sponge_x4_stats stats=keccak_sponge_x4_get_stats();
        if (stats.hardware_absorbs==0 || (!timeout_path && stats.hardware_squeeze_blocks==0)) return 8;
        if (timeout_path && stats.timeout_fallbacks!=1) return 9;
        if (!timeout_path && stats.timeout_fallbacks!=0) return 10;
        printf("MLKEM_SX4_ACVP operation=%s path=%s result=PASS hardware_absorbs=%u hardware_squeezes=%u timeout_fallbacks=%u\n",
            argv[1],argv[2],stats.hardware_absorbs,stats.hardware_squeeze_blocks,stats.timeout_fallbacks);
    }
    if (!write_exact(argv[5],output,output_len)) return 6;
    return 0;
}
