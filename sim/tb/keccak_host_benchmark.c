#include "mlkem/mlkem_native.h"
#include "mlkem/src/fips202/keccakf1600.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
static uint64_t ticks(void) {
  LARGE_INTEGER value;
  QueryPerformanceCounter(&value);
  return (uint64_t)value.QuadPart;
}
static uint64_t tick_frequency(void) {
  LARGE_INTEGER value;
  QueryPerformanceFrequency(&value);
  return (uint64_t)value.QuadPart;
}
#else
#include <time.h>
static uint64_t ticks(void) {
  struct timespec value;
  clock_gettime(CLOCK_MONOTONIC, &value);
  return (uint64_t)value.tv_sec * UINT64_C(1000000000) + (uint64_t)value.tv_nsec;
}
static uint64_t tick_frequency(void) { return UINT64_C(1000000000); }
#endif

static int load_exact(const char *path, uint8_t *dst, size_t size) {
  FILE *f = fopen(path, "rb");
  if (!f) return 0;
  int ok = fread(dst, 1, size, f) == size && fgetc(f) == EOF;
  fclose(f);
  return ok;
}

static uint64_t checksum_state(const uint64_t state[25]) {
  uint64_t sum = 0;
  for (unsigned i = 0; i < 25; ++i) sum ^= state[i] + (sum << 7) + (sum >> 3);
  return sum;
}

static void sort9(uint64_t values[9]) {
  for (unsigned i = 1; i < 9; ++i) {
    uint64_t v = values[i]; unsigned j = i;
    while (j && values[j - 1] > v) { values[j] = values[j - 1]; --j; }
    values[j] = v;
  }
}

int main(int argc, char **argv) {
  if (argc != 5) {
    fprintf(stderr, "usage: %s <decap-input.bin> <expected-ss.bin> <state-in.bin> <state-out.bin>\n", argv[0]);
    return 2;
  }
  uint8_t decap[MLKEM512_SECRETKEYBYTES + MLKEM512_CIPHERTEXTBYTES];
  uint8_t expected_ss[MLKEM_BYTES], ss[MLKEM_BYTES];
  uint64_t state[25], initial_state[25], expected_state[25];
  if (!load_exact(argv[1], decap, sizeof decap) ||
      !load_exact(argv[2], expected_ss, sizeof expected_ss) ||
      !load_exact(argv[3], (uint8_t *)state, sizeof state) ||
      !load_exact(argv[4], (uint8_t *)expected_state, sizeof expected_state)) {
    fprintf(stderr, "input vector file size/read error\n"); return 2;
  }
  memcpy(initial_state, state, sizeof state);
  const uint8_t *sk = decap;
  const uint8_t *ct = decap + MLKEM512_SECRETKEYBYTES;
  uint64_t frequency = tick_frequency();
  if (!frequency) { fprintf(stderr, "clock frequency unavailable\n"); return 2; }

  for (unsigned i = 0; i < 32; ++i) eye_mlkem_keccakf1600_permute(state);
  memcpy(state, initial_state, sizeof state);
  eye_mlkem_keccakf1600_permute(state);
  if (memcmp(state, expected_state, sizeof state) != 0) {
    fprintf(stderr, "Keccak reference mismatch lane0=%016" PRIx64 " expected=%016" PRIx64 "\n", state[0], expected_state[0]); return 3;
  }
  memcpy(state, initial_state, sizeof state);
  uint64_t perm_ticks[9];
  uint64_t sink = checksum_state(state);
  for (unsigned b = 0; b < 9; ++b) {
    uint64_t start = ticks();
    for (unsigned i = 0; i < 10000; ++i) eye_mlkem_keccakf1600_permute(state);
    perm_ticks[b] = ticks() - start;
    sink ^= checksum_state(state);
  }

  for (unsigned i = 0; i < 3; ++i) {
    if (eye_mlkem_dec(ss, ct, sk) != 0 || memcmp(ss, expected_ss, sizeof ss) != 0) {
      fprintf(stderr, "ML-KEM KAT mismatch during warmup\n"); return 4;
    }
  }
  uint64_t dec_ticks[9];
  for (unsigned b = 0; b < 9; ++b) {
    uint64_t start = ticks();
    for (unsigned i = 0; i < 20; ++i) {
      if (eye_mlkem_dec(ss, ct, sk) != 0 || memcmp(ss, expected_ss, sizeof ss) != 0) {
        fprintf(stderr, "ML-KEM KAT mismatch at batch %u item %u\n", b, i); return 4;
      }
    }
    dec_ticks[b] = ticks() - start;
    sink ^= ss[b % sizeof ss];
  }
  sort9(perm_ticks); sort9(dec_ticks);
  printf("HOST_BENCH_OK clock_ticks_per_second=%" PRIu64 " permutation_warmup=32 permutation_ops_per_sample=10000 permutation_samples=9 permutation_ticks=", frequency);
  for (unsigned i = 0; i < 9; ++i) printf("%s%" PRIu64, i ? "," : "", perm_ticks[i]);
  printf(" permutation_median_ticks_per_op=%.3f permutation_p95_ticks_per_op=%.3f decap_warmup=3 decap_ops_per_sample=20 decap_samples=9 decap_ticks=", (double)perm_ticks[4] / 10000.0, (double)perm_ticks[8] / 10000.0);
  for (unsigned i = 0; i < 9; ++i) printf("%s%" PRIu64, i ? "," : "", dec_ticks[i]);
  printf(" decap_median_ticks_per_op=%.3f decap_p95_ticks_per_op=%.3f sink=%016" PRIx64 "\n", (double)dec_ticks[4] / 20.0, (double)dec_ticks[8] / 20.0, sink);
  memset(ss, 0, sizeof ss);
  memset(state, 0, sizeof state);
  return 0;
}
