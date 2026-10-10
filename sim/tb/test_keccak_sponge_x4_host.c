#include "keccak_sponge_x4.h"
#include "keccak_sponge_x4_hostmock.h"
#include "mlkem_sponge_fips202x4_custom.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

void eye_mlkem_ref_keccakf1600x4_permute(uint64_t state[100]);
void eye_mlkem_ref_keccakf1600x4_extract_bytes(uint64_t state[100],
    unsigned char *o0,unsigned char *o1,unsigned char *o2,unsigned char *o3,
    unsigned offset,unsigned length);
void eye_mlkem_ref_keccakf1600x4_xor_bytes(uint64_t state[100],
    const unsigned char *i0,const unsigned char *i1,const unsigned char *i2,
    const unsigned char *i3,unsigned offset,unsigned length);

typedef struct {
    uint32_t input_words[172], output_words[168];
    uint64_t state[4][25];
    uint32_t status, id, version, input_len;
    uint32_t reads, writes, launches, clears, state_writes, command_number;
    uint32_t fail_command;
    int fail_timeout;
    uint8_t *watch[4];
    size_t watch_bytes;
    uint8_t watch_value;
    int clear_preserved_output;
} mock_sx4;

extern mock_sx4 g_mock;

static uint8_t get_input(const mock_sx4 *m,unsigned lane,unsigned at)
{
    uint32_t word=m->input_words[lane*43u+at/4u];
    return (uint8_t)(word>>(8u*(at&3u)));
}

static void mock_clear(mock_sx4 *m)
{
    memset(m->state,0,sizeof m->state);
    memset(m->input_words,0,sizeof m->input_words);
    memset(m->output_words,0,sizeof m->output_words);
    m->status=0; m->input_len=0; ++m->clears;
    if (m->watch[0]) {
        m->clear_preserved_output=1;
        for (unsigned lane=0;lane<4;++lane)
            for (size_t i=0;i<m->watch_bytes;++i)
                if (m->watch[lane][i]!=m->watch_value) m->clear_preserved_output=0;
    }
}

static void do_absorb(mock_sx4 *m)
{
    uint64_t states[100]={0};
    if (m->input_len>=168) {
        for (unsigned lane=0;lane<4;++lane)
            for (unsigned i=0;i<168;++i) {
                uint8_t byte=get_input(m,lane,i);
                states[lane*25u+i/8u]^=(uint64_t)byte<<(8u*(i&7u));
            }
        eye_mlkem_ref_keccakf1600x4_permute(states);
    }
    /* Model all four independent SHAKE128 final padded states, retaining the
       post-full-block state when the input crosses the rate. */
    for (unsigned lane=0;lane<4;++lane) {
        unsigned rem=m->input_len%168u;
        unsigned offset=m->input_len-rem;
        if (m->input_len>=168) memcpy(m->state[lane],states+lane*25u,200);
        else memset(m->state[lane],0,sizeof m->state[lane]);
        for (unsigned i=0;i<rem;++i) {
            uint8_t b=get_input(m,lane,offset+i);
            m->state[lane][i/8]^=(uint64_t)b<<(8u*(i&7u));
        }
        if (rem==167) m->state[lane][20]^=UINT64_C(0x9f00000000000000);
        else {
            m->state[lane][rem/8]^=(uint64_t)0x1f<<(8u*(rem&7u));
            m->state[lane][20]^=UINT64_C(0x8000000000000000);
        }
    }
    memset(states,0,sizeof states);
}

uint32_t sx4_hostmock_read32(void *opaque,uint32_t off)
{
    mock_sx4 *m=opaque; ++m->reads;
    if (off==KECCAK_SX4_ID_OFFSET) return m->id;
    if (off==KECCAK_SX4_VERSION_OFFSET) return m->version;
    if (off==KECCAK_SX4_STATUS_OFFSET) return m->status;
    if (off==KECCAK_SX4_INLEN_OFFSET) return m->input_len;
    if (off>=KECCAK_SX4_OUTPUT_OFFSET && off<KECCAK_SX4_OUTPUT_OFFSET+672u)
        return m->output_words[(off-KECCAK_SX4_OUTPUT_OFFSET)/4u];
    return 0;
}

void sx4_hostmock_write32(void *opaque,uint32_t off,uint32_t value)
{
    mock_sx4 *m=opaque; ++m->writes;
    if (off==KECCAK_SX4_CTRL_OFFSET) {
        if (value==KECCAK_SX4_CTRL_CLEAR) { mock_clear(m); return; }
        ++m->launches; ++m->command_number;
        m->status=KECCAK_SX4_STATUS_BUSY;
        if (m->fail_command==m->command_number) {
            m->status=m->fail_timeout ? KECCAK_SX4_STATUS_ERROR|KECCAK_SX4_STATUS_TIMEOUT
                                      : KECCAK_SX4_STATUS_ERROR;
            return;
        }
        if (value==KECCAK_SX4_CTRL_ABSORB) do_absorb(m);
        else if (value==KECCAK_SX4_CTRL_SQUEEZE) {
            uint64_t lanes[100];
            uint8_t out[4][168];
            uint64_t *out_lanes[4]={m->state[0],m->state[1],m->state[2],m->state[3]};
            memcpy(lanes,m->state,sizeof lanes);
            eye_mlkem_ref_keccakf1600x4_permute(lanes);
            for (unsigned l=0;l<4;++l) memcpy(m->state[l],lanes+25*l,200);
            eye_mlkem_ref_keccakf1600x4_extract_bytes(lanes,out[0],out[1],out[2],out[3],0,168);
            for (unsigned l=0;l<4;++l)
                for (unsigned w=0;w<42;++w)
                    m->output_words[l*42+w]=(uint32_t)out[l][w*4] |
                        ((uint32_t)out[l][w*4+1]<<8) |
                        ((uint32_t)out[l][w*4+2]<<16) |
                        ((uint32_t)out[l][w*4+3]<<24);
            (void)out_lanes;
            memset(lanes,0,sizeof lanes); memset(out,0,sizeof out);
        }
        m->status=KECCAK_SX4_STATUS_DONE|KECCAK_SX4_STATUS_CONTEXT;
        return;
    }
    if (off==KECCAK_SX4_INLEN_OFFSET) { m->input_len=value; return; }
    if (off>=KECCAK_SX4_INPUT_OFFSET && off<KECCAK_SX4_INPUT_OFFSET+688u) {
        unsigned index=(off-KECCAK_SX4_INPUT_OFFSET)/4u;
        m->input_words[index]=value; ++m->state_writes;
    }
}

#ifndef SX4_HOSTMOCK_LIBRARY
static void reference_x4(const uint8_t *in[4],size_t inlen,
                         uint8_t *out[4],size_t nblocks)
{
    uint64_t state[100]={0};
    size_t remain=inlen, offset=0;
    while (remain>=168) {
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state,in[0]+offset,in[1]+offset,
            in[2]+offset,in[3]+offset,0,168);
        eye_mlkem_ref_keccakf1600x4_permute(state); offset+=168; remain-=168;
    }
    if (remain) eye_mlkem_ref_keccakf1600x4_xor_bytes(state,in[0]+offset,
        in[1]+offset,in[2]+offset,in[3]+offset,0,(unsigned)remain);
    if (remain==167) {
        uint8_t d=0x9f;
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state,&d,&d,&d,&d,167,1);
    } else {
        uint8_t d=0x1f, high=0x80;
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state,&d,&d,&d,&d,(unsigned)remain,1);
        eye_mlkem_ref_keccakf1600x4_xor_bytes(state,&high,&high,&high,&high,167,1);
    }
    for (size_t b=0;b<nblocks;++b) {
        eye_mlkem_ref_keccakf1600x4_permute(state);
        eye_mlkem_ref_keccakf1600x4_extract_bytes(state,out[0]+b*168,
            out[1]+b*168,out[2]+b*168,out[3]+b*168,0,168);
    }
    memset(state,0,sizeof state);
}

static int run_context(const char *label,const uint8_t input[4][169],size_t inlen,
                       size_t nblocks,uint32_t fail_at,int timeout,
                       int expect_hardware)
{
    mlk_shake128x4ctx ctx;
    uint8_t got[4][12*168],expected[4][12*168];
    const uint8_t *in[4]={input[0],input[1],input[2],input[3]};
    uint8_t *ref[4]={expected[0],expected[1],expected[2],expected[3]};
    memset(&ctx,0,sizeof ctx); memset(got,0xa5,sizeof got);
    reference_x4(in,inlen,ref,nblocks);
    mlk_shake128x4_absorb_once(&ctx,in[0],in[1],in[2],in[3],inlen);
    if (fail_at) {
        /* Caller output must remain untouched through failed hardware and the
           successful clear; fallback then replaces the complete output. */
        g_mock.watch[0]=got[0]; g_mock.watch[1]=got[1];
        g_mock.watch[2]=got[2]; g_mock.watch[3]=got[3];
        g_mock.watch_bytes=nblocks*168; g_mock.watch_value=0xa5;
        g_mock.fail_command=fail_at; g_mock.fail_timeout=timeout;
    }
    mlk_shake128x4_squeezeblocks(got[0],got[1],got[2],got[3],nblocks,&ctx);
    for (unsigned lane=0;lane<4;++lane)
        if (memcmp(got[lane],expected[lane],nblocks*168)!=0) {
            fprintf(stderr,"x4 mock mismatch %s lane=%u\n",label,lane); return 0;
        }
    if (fail_at && !g_mock.clear_preserved_output) {
        fprintf(stderr,"failed output was committed before clear in %s\n",label); return 0;
    }
    if (expect_hardware && g_mock.launches==0) return 0;
    printf("SX4_HOST_CASE case=%s blocks=%zu correct=1\n",label,nblocks);
    mlk_shake128x4_release(&ctx);
    return 1;
}
#endif

mock_sx4 g_mock;

#ifdef SX4_HOSTMOCK_LIBRARY
void sx4_hostmock_reset(uint32_t id,uint32_t version)
{
    memset(&g_mock,0,sizeof g_mock);
    g_mock.id=id; g_mock.version=version;
}

void *sx4_hostmock_opaque(void) { return &g_mock; }

void sx4_hostmock_set_failure(uint32_t command_number,int timeout)
{
    g_mock.fail_command=command_number;
    g_mock.fail_timeout=timeout;
}

uint32_t sx4_hostmock_launches(void) { return g_mock.launches; }
uint32_t sx4_hostmock_state_writes(void) { return g_mock.state_writes; }
uint32_t sx4_hostmock_command_number(void) { return g_mock.command_number; }
#else
int main(void)
{
    keccak_accel_io io={&g_mock,sx4_hostmock_read32,sx4_hostmock_write32,KECCAK_ACCEL_EXPERIMENTAL_ENABLE};
    uint8_t inputs[4][169];
    uint64_t rng=UINT64_C(0x819a5f327c04d6e1);
    for (unsigned l=0;l<4;++l) for (unsigned i=0;i<169;++i) {
        rng^=rng<<13; rng^=rng>>7; rng^=rng<<17; inputs[l][i]=(uint8_t)rng;
    }
    memset(&g_mock,0,sizeof g_mock); g_mock.id=KECCAK_SX4_ID_VALUE;
    g_mock.version=KECCAK_SX4_VERSION_VALUE;
    if (!keccak_sponge_x4_configure(&io,32)) return 2;
    if (!run_context("random_3_blocks",inputs,34,3,0,0,1)) return 3;
    if (!run_context("rate_minus_one_167",inputs,167,2,0,0,1)) return 18;
    if (!run_context("full_rate_168",inputs,168,2,0,0,1)) return 19;
    if (!run_context("rate_plus_one_169",inputs,169,2,0,0,1)) return 20;

    /* One x4 slot: replacing the owner invalidates only the old context;
       releasing the old generation must not clear the new live slot. */
    {
        mlk_shake128x4ctx a,b;
        uint8_t other[4][169], outa[4][168], outb[4][168], refa[4][2*168], refb[4][168];
        const uint8_t *ain[4]={inputs[0],inputs[1],inputs[2],inputs[3]};
        const uint8_t *bin[4]={other[0],other[1],other[2],other[3]};
        uint8_t *ao[4]={outa[0],outa[1],outa[2],outa[3]}, *bo[4]={outb[0],outb[1],outb[2],outb[3]};
        uint8_t *ar[4]={refa[0],refa[1],refa[2],refa[3]}, *br[4]={refb[0],refb[1],refb[2],refb[3]};
        for (unsigned l=0;l<4;++l) for (unsigned i=0;i<169;++i) other[l][i]=(uint8_t)(inputs[l][i]^0x96u);
        reference_x4(ain,34,ar,2); reference_x4(bin,34,br,1);
        mlk_shake128x4_absorb_once(&a,ain[0],ain[1],ain[2],ain[3],34);
        mlk_shake128x4_squeezeblocks(ao[0],ao[1],ao[2],ao[3],1,&a);
        mlk_shake128x4_absorb_once(&b,bin[0],bin[1],bin[2],bin[3],34);
        mlk_shake128x4_squeezeblocks(ao[0],ao[1],ao[2],ao[3],1,&a);
        for (unsigned l=0;l<4;++l)
            if (memcmp(ao[l],ar[l]+168,168)!=0) return 5;
        { uint32_t clears=g_mock.clears; mlk_shake128x4_release(&a);
          if (g_mock.clears!=clears) return 6; }
        mlk_shake128x4_squeezeblocks(bo[0],bo[1],bo[2],bo[3],1,&b);
        for (unsigned l=0;l<4;++l)
            if (memcmp(bo[l],br[l],168)!=0) return 7;
        puts("SX4_HOST_CONTEXT_PASS alternating_contexts=1 stale_release_preserves_owner=1 stale_replay=1");
        mlk_shake128x4_release(&b); mlk_shake128x4_release(&a);
    }

    memset(&g_mock,0,sizeof g_mock); g_mock.id=KECCAK_SX4_ID_VALUE;
    g_mock.version=KECCAK_SX4_VERSION_VALUE;
    if (!keccak_sponge_x4_configure(&io,32)) return 7;
    g_mock.fail_command=3; g_mock.fail_timeout=1; /* absorb, good block, timeout block 2 */
    if (!run_context("mid_timeout_3_blocks",inputs,34,3,3,1,1)) return 8;

    memset(&g_mock,0,sizeof g_mock); g_mock.id=KECCAK_SX4_ID_VALUE;
    g_mock.version=KECCAK_SX4_VERSION_VALUE;
    if (!keccak_sponge_x4_configure(&io,32)) return 9;
    g_mock.fail_command=3; g_mock.fail_timeout=0;
    if (!run_context("mid_error_3_blocks",inputs,34,3,3,0,1)) return 10;

    memset(&g_mock,0,sizeof g_mock); g_mock.id=KECCAK_SX4_ID_VALUE;
    g_mock.version=KECCAK_SX4_VERSION_VALUE;
    if (!keccak_sponge_x4_configure(&io,32)) return 11;
    if (!run_context("request_9_blocks",inputs,34,9,0,0,0)) return 12;

    memset(&g_mock,0,sizeof g_mock); g_mock.id=KECCAK_SX4_ID_VALUE;
    g_mock.version=KECCAK_SX4_VERSION_VALUE;
    if (!keccak_sponge_x4_configure(&io,32)) return 13;
    {
        mlk_shake128x4ctx ctx; uint8_t got[4][10*168],expected[4][10*168];
        const uint8_t *in[4]={inputs[0],inputs[1],inputs[2],inputs[3]};
        uint8_t *out[4]={got[0],got[1],got[2],got[3]},*ref[4]={expected[0],expected[1],expected[2],expected[3]};
        reference_x4(in,34,ref,10); mlk_shake128x4_absorb_once(&ctx,in[0],in[1],in[2],in[3],34);
        mlk_shake128x4_squeezeblocks(out[0],out[1],out[2],out[3],5,&ctx);
        mlk_shake128x4_squeezeblocks(out[0]+5*168,out[1]+5*168,out[2]+5*168,out[3]+5*168,5,&ctx);
        for (unsigned l=0;l<4;++l) if (memcmp(got[l],expected[l],10*168)!=0) return 14;
        puts("SX4_HOST_CONTEXT_PASS cumulative_blocks_gt8=1 second_call_fallback_persistent_state=1");
        mlk_shake128x4_release(&ctx);
    }
    memset(&g_mock,0,sizeof g_mock); g_mock.id=KECCAK_SX4_ID_VALUE ^ 1u;
    g_mock.version=KECCAK_SX4_VERSION_VALUE;
    if (keccak_sponge_x4_configure(&io,32)) return 15;
    if (!run_context("identity_failure_software",inputs,34,2,0,0,0)) return 16;
    if (g_mock.state_writes!=0 || g_mock.launches!=0) return 17;
    puts("SX4_HOST_IDENTITY_PASS mismatch_fallback=1 state_writes=0 start=0");
    puts("KECCAK_SX4_HOST_PASS identity_generation=1 timeout_replay=1 error_replay=1 caller_output_atomic=1 request_gt8=1 cumulative_gt8=1");
    return 0;
}
#endif
