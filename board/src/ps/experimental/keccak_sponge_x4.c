#include "keccak_sponge_x4.h"
#include "mlkem_sponge_fips202x4_custom.h"

#include <limits.h>
#include <string.h>

/* Reference x4 primitives are separately compiled under eye_mlkem_ref. */
void eye_mlkem_ref_keccakf1600x4_permute(uint64_t state[100]);
void eye_mlkem_ref_keccakf1600x4_extract_bytes(uint64_t state[100],
    unsigned char *out0, unsigned char *out1, unsigned char *out2,
    unsigned char *out3, unsigned offset, unsigned length);
void eye_mlkem_ref_keccakf1600x4_xor_bytes(uint64_t state[100],
    const unsigned char *in0, const unsigned char *in1,
    const unsigned char *in2, const unsigned char *in3,
    unsigned offset, unsigned length);

#define SX4_META_MAGIC UINT32_C(0x58463453)
typedef struct {
    uint32_t magic;
    uint32_t magic_inverse;
    uint64_t generation;
    uint64_t completed_blocks;
    uint32_t input_length;
    uint32_t reserved;
    uint8_t input[4][KECCAK_SX4_MAX_INPUT_BYTES];
} sx4_context_meta;

_Static_assert(sizeof(sx4_context_meta) <= sizeof(((mlk_shake128x4ctx *)0)->ctx),
               "x4 opaque context must fit in the vendored context ABI");
_Static_assert(sizeof(((mlk_shake128x4ctx *)0)->ctx) == 800,
               "unexpected vendored x4 context ABI size");

static keccak_accel_io active_io;
static uint32_t active_poll_limit;
static uint64_t active_generation;
static uint64_t active_completed_blocks;
static int active_identity_valid;
static int active_context_valid;
static keccak_sponge_x4_stats stats;

static void io_barrier(void)
{
#if defined(__arm__) || defined(__aarch64__)
    __asm__ volatile("dmb sy" ::: "memory");
#else
    __asm__ volatile("" ::: "memory");
#endif
}

static void write32(uint32_t offset, uint32_t value)
{
    active_io.write32(active_io.opaque, offset, value);
    io_barrier();
}

static uint32_t read32(uint32_t offset)
{
    uint32_t value = active_io.read32(active_io.opaque, offset);
    io_barrier();
    return value;
}

static int wait_command(uint32_t *final_status)
{
    uint32_t i, status = 0;
    for (i = 0; i < active_poll_limit; ++i) {
        status = read32(KECCAK_SX4_STATUS_OFFSET);
        if (status & (KECCAK_SX4_STATUS_ERROR | KECCAK_SX4_STATUS_TIMEOUT)) {
            *final_status = status;
            return 0;
        }
        if ((status & KECCAK_SX4_STATUS_BUSY) == 0) {
            *final_status = status;
            return (status & (KECCAK_SX4_STATUS_DONE | KECCAK_SX4_STATUS_CONTEXT)) ==
                   (KECCAK_SX4_STATUS_DONE | KECCAK_SX4_STATUS_CONTEXT);
        }
    }
    *final_status = status;
    return 0;
}

static int clear_device(void)
{
    uint32_t status;
    write32(KECCAK_SX4_CTRL_OFFSET, KECCAK_SX4_CTRL_CLEAR);
    status = read32(KECCAK_SX4_STATUS_OFFSET);
    if (status == 0) {
        active_context_valid = 0;
        active_completed_blocks = 0;
        return 1;
    }
    active_context_valid = 0;
    active_identity_valid = 0;
    return 0;
}

int keccak_sponge_x4_configure(const keccak_accel_io *io, uint32_t poll_limit)
{
    if (io != NULL) active_io = *io;
    else memset(&active_io, 0, sizeof active_io);
    active_poll_limit = poll_limit;
    active_identity_valid = 0;
    active_context_valid = 0;
    active_completed_blocks = 0;
    ++active_generation;
    if (active_generation == 0) ++active_generation;
    if (active_io.activation_cookie == KECCAK_ACCEL_EXPERIMENTAL_ENABLE &&
        active_io.read32 != NULL && active_io.write32 != NULL && poll_limit != 0) {
        uint32_t id = read32(KECCAK_SX4_ID_OFFSET);
        uint32_t version = read32(KECCAK_SX4_VERSION_OFFSET);
        active_identity_valid = id == KECCAK_SX4_ID_VALUE &&
                                version == KECCAK_SX4_VERSION_VALUE;
        if (active_identity_valid && !clear_device()) active_identity_valid = 0;
    }
    return active_identity_valid;
}

void keccak_sponge_x4_reset_stats(void) { memset(&stats, 0, sizeof stats); }
keccak_sponge_x4_stats keccak_sponge_x4_get_stats(void) { return stats; }

static void store_meta(mlk_shake128x4ctx *state, const sx4_context_meta *meta)
{
    memset(state, 0, sizeof *state);
    memcpy(state->ctx, meta, sizeof *meta);
}

static int load_meta(const mlk_shake128x4ctx *state, sx4_context_meta *meta)
{
    memcpy(meta, state->ctx, sizeof *meta);
    return meta->magic == SX4_META_MAGIC &&
           meta->magic_inverse == ~SX4_META_MAGIC &&
           meta->input_length <= KECCAK_SX4_MAX_INPUT_BYTES;
}

static void software_absorb_x4(uint64_t state[100], const uint8_t *in[4],
                               size_t inlen, unsigned rate, uint8_t delimiter)
{
    size_t remaining = inlen;
    const uint8_t *cursor[4] = {in[0], in[1], in[2], in[3]};
    memset(state, 0, sizeof(uint64_t) * 100);
    while (remaining >= rate) {
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state, cursor[0], cursor[1],
            cursor[2], cursor[3], 0, rate);
        eye_mlkem_ref_keccakf1600x4_permute(state);
        for (unsigned lane=0; lane<4; ++lane) cursor[lane] += rate;
        remaining -= rate;
    }
    if (remaining != 0)
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state, cursor[0], cursor[1],
            cursor[2], cursor[3], 0, (unsigned)remaining);
    if (remaining == rate - 1) {
        uint8_t final_delimiter = (uint8_t)(delimiter | 0x80u);
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state, &final_delimiter,
            &final_delimiter, &final_delimiter, &final_delimiter,
            (unsigned)remaining, 1);
    } else {
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state, &delimiter, &delimiter,
            &delimiter, &delimiter, (unsigned)remaining, 1);
        {
            uint8_t final_bit = 0x80;
            eye_mlkem_ref_keccakf1600x4_xor_bytes(state, &final_bit, &final_bit,
                &final_bit, &final_bit, rate - 1, 1);
        }
    }
}

static void software_squeeze_x4(uint64_t state[100], uint8_t *out[4],
                                size_t nblocks, unsigned rate)
{
    for (size_t block=0; block<nblocks; ++block) {
        eye_mlkem_ref_keccakf1600x4_permute(state);
        eye_mlkem_ref_keccakf1600x4_extract_bytes(state,
            out[0] + block*rate, out[1] + block*rate,
            out[2] + block*rate, out[3] + block*rate, 0, rate);
    }
}

static int hardware_absorb(const uint8_t *input[4], size_t inlen)
{
    uint32_t final_status;
    unsigned words, w, lane, b;
    if (!active_identity_valid || inlen > KECCAK_SX4_MAX_INPUT_BYTES) return 0;
    write32(KECCAK_SX4_INLEN_OFFSET, (uint32_t)inlen);
    words = (unsigned)((inlen + 3u) / 4u);
    for (w=0; w<words; ++w) {
        for (lane=0; lane<4; ++lane) {
            uint32_t value=0;
            for (b=0; b<4; ++b) {
                size_t at=(size_t)w*4u+b;
                if (at<inlen) value |= (uint32_t)input[lane][at] << (8u*b);
            }
            write32(KECCAK_SX4_INPUT_OFFSET + (lane*43u+w)*4u, value);
        }
    }
    io_barrier();
    write32(KECCAK_SX4_CTRL_OFFSET, KECCAK_SX4_CTRL_ABSORB);
    if (!wait_command(&final_status)) {
        if (final_status & KECCAK_SX4_STATUS_TIMEOUT) ++stats.timeout_fallbacks;
        else ++stats.error_fallbacks;
        (void)clear_device();
        return 0;
    }
    active_context_valid=1;
    active_completed_blocks=0;
    ++stats.hardware_absorbs;
    return 1;
}

static int hardware_squeeze_block(uint8_t out[4][KECCAK_SX4_RATE_BYTES])
{
    uint32_t final_status, word;
    unsigned lane, w, b;
    write32(KECCAK_SX4_CTRL_OFFSET, KECCAK_SX4_CTRL_SQUEEZE);
    if (!wait_command(&final_status)) {
        if (final_status & KECCAK_SX4_STATUS_TIMEOUT) ++stats.timeout_fallbacks;
        else ++stats.error_fallbacks;
        return 0;
    }
    for (lane=0; lane<4; ++lane) {
        for (w=0; w<42; ++w) {
            word=read32(KECCAK_SX4_OUTPUT_OFFSET+(lane*42u+w)*4u);
            for (b=0; b<4; ++b) out[lane][w*4u+b]=(uint8_t)(word>>(8u*b));
        }
    }
    final_status=read32(KECCAK_SX4_STATUS_OFFSET);
    if ((final_status & (KECCAK_SX4_STATUS_DONE | KECCAK_SX4_STATUS_CONTEXT)) !=
            (KECCAK_SX4_STATUS_DONE | KECCAK_SX4_STATUS_CONTEXT) ||
        (final_status & (KECCAK_SX4_STATUS_ERROR | KECCAK_SX4_STATUS_TIMEOUT))) {
        ++stats.error_fallbacks;
        return 0;
    }
    ++active_completed_blocks;
    ++stats.hardware_squeeze_blocks;
    return 1;
}

void mlk_shake128x4_init(mlk_shake128x4ctx *state)
{
    if (state != NULL) memset(state, 0, sizeof *state);
}

void mlk_shake128x4_absorb_once(mlk_shake128x4ctx *state,
    const uint8_t *in0, const uint8_t *in1, const uint8_t *in2,
    const uint8_t *in3, size_t inlen)
{
    const uint8_t *inputs[4]={in0,in1,in2,in3};
    sx4_context_meta meta;
    ++stats.absorb_calls;
    if (state == NULL || in0 == NULL || in1 == NULL || in2 == NULL || in3 == NULL) return;
    if (active_identity_valid && inlen <= KECCAK_SX4_MAX_INPUT_BYTES) {
        memset(&meta,0,sizeof meta);
        meta.magic=SX4_META_MAGIC; meta.magic_inverse=~SX4_META_MAGIC;
        ++active_generation;
        if (active_generation == 0) ++active_generation;
        meta.generation=active_generation; meta.input_length=(uint32_t)inlen;
        for (unsigned lane=0; lane<4; ++lane)
            if (inlen != 0) memcpy(meta.input[lane],inputs[lane],inlen);
        if (hardware_absorb(inputs,inlen)) {
            store_meta(state,&meta);
            return;
        }
        ++stats.software_fallbacks;
    }
    software_absorb_x4(state->ctx,inputs,inlen,SHAKE128_RATE,0x1f);
}

static void fallback_squeeze(const sx4_context_meta *meta, size_t nblocks,
                             uint8_t *out[4], mlk_shake128x4ctx *context)
{
    uint64_t sw_state[100];
    uint8_t discard[4][KECCAK_SX4_RATE_BYTES];
    const uint8_t *inputs[4]={meta->input[0],meta->input[1],meta->input[2],meta->input[3]};
    uint8_t *discard_ptrs[4]={discard[0],discard[1],discard[2],discard[3]};
    software_absorb_x4(sw_state,inputs,meta->input_length,SHAKE128_RATE,0x1f);
    for (uint64_t b=0;b<meta->completed_blocks;++b)
        software_squeeze_x4(sw_state,discard_ptrs,1,SHAKE128_RATE);
    software_squeeze_x4(sw_state,out,nblocks,SHAKE128_RATE);
    memcpy(context->ctx,sw_state,sizeof sw_state);
    memset(sw_state,0,sizeof sw_state);
    memset(discard,0,sizeof discard);
}

void mlk_shake128x4_squeezeblocks(uint8_t *out0,uint8_t *out1,
    uint8_t *out2,uint8_t *out3,size_t nblocks,mlk_shake128x4ctx *state)
{
    uint8_t *outputs[4]={out0,out1,out2,out3};
    sx4_context_meta meta;
    uint8_t staged[4][KECCAK_SX4_RATE_BYTES * KECCAK_SX4_MAX_BLOCKS];
    uint8_t block[4][KECCAK_SX4_RATE_BYTES];
    size_t complete=0;
    if (state==NULL || nblocks==0 || nblocks>SIZE_MAX/KECCAK_SX4_RATE_BYTES ||
        out0==NULL || out1==NULL || out2==NULL || out3==NULL) return;
    if (!load_meta(state,&meta)) {
        software_squeeze_x4(state->ctx,outputs,nblocks,SHAKE128_RATE);
        return;
    }
    if (active_identity_valid && active_context_valid &&
        meta.generation==active_generation &&
        meta.completed_blocks==active_completed_blocks &&
        nblocks<=KECCAK_SX4_MAX_BLOCKS &&
        meta.completed_blocks<=UINT64_MAX-(uint64_t)nblocks) {
        for (;complete<nblocks;++complete) {
            if (!hardware_squeeze_block(block)) break;
            for (unsigned lane=0;lane<4;++lane)
                memcpy(staged[lane]+complete*SHAKE128_RATE,block[lane],SHAKE128_RATE);
        }
        if (complete==nblocks) {
            for (unsigned lane=0;lane<4;++lane)
                memcpy(outputs[lane],staged[lane],nblocks*SHAKE128_RATE);
            meta.completed_blocks+=(uint64_t)nblocks;
            store_meta(state,&meta);
            memset(staged,0,sizeof staged); memset(block,0,sizeof block);
            return;
        }
        /* The context's original input and completed block count are intact.
         * Clear the matching hardware slot before software reconstruction. */
        (void)clear_device();
        ++stats.software_fallbacks;
    }
    if (active_context_valid && meta.generation==active_generation)
        (void)clear_device();
    (void)complete; /* replay below overwrites all provisional caller bytes */
    fallback_squeeze(&meta,nblocks,outputs,state);
    memset(staged,0,sizeof staged); memset(block,0,sizeof block);
}

void mlk_shake128x4_release(mlk_shake128x4ctx *state)
{
    sx4_context_meta meta;
    if (state==NULL) return;
    if (load_meta(state,&meta) && active_context_valid &&
        meta.generation==active_generation) (void)clear_device();
    memset(state,0,sizeof *state);
}

void mlk_shake256x4(uint8_t *out0,uint8_t *out1,uint8_t *out2,uint8_t *out3,
    size_t outlen,const uint8_t *in0,const uint8_t *in1,
    const uint8_t *in2,const uint8_t *in3,size_t inlen)
{
    uint64_t state[100];
    uint8_t *out[4]={out0,out1,out2,out3};
    const uint8_t *in[4]={in0,in1,in2,in3};
    size_t nblocks=outlen/SHAKE256_RATE, tail=outlen%SHAKE256_RATE;
    uint8_t tmp[4][SHAKE256_RATE];
    if (!outlen) return;
    software_absorb_x4(state,in,inlen,SHAKE256_RATE,0x1f);
    if (nblocks) software_squeeze_x4(state,out,nblocks,SHAKE256_RATE);
    if (tail) {
        uint8_t *tmp_ptrs[4]={tmp[0],tmp[1],tmp[2],tmp[3]};
        software_squeeze_x4(state,tmp_ptrs,1,SHAKE256_RATE);
        for (unsigned lane=0;lane<4;++lane) memcpy(out[lane]+nblocks*SHAKE256_RATE,tmp[lane],tail);
    }
    memset(state,0,sizeof state); memset(tmp,0,sizeof tmp);
}
