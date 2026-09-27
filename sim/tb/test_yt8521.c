/* Tiny MDIO model: actual adapter C, no board writes or cloned driver. */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef uint16_t u16_t;
typedef uint32_t u32_t;
typedef struct { int unused; } XEmacPs;
#define XST_SUCCESS 0
#define XST_FAILURE 1
#define xil_printf(...) ((void)printf(__VA_ARGS__))
static u16_t regs[32], ext[65536], selected;
static unsigned int delays, writes, resets;
static int bad_read, bad_write, stuck_reset;
static int XEmacPs_PhyRead(XEmacPs *mac, u32_t addr, u32_t reg, u16_t *value)
{
    (void)mac; (void)addr;
    if (bad_read) return XST_FAILURE;
    *value = reg == 0x1f ? ext[selected] : regs[reg];
    return XST_SUCCESS;
}
static int XEmacPs_PhyWrite(XEmacPs *mac, u32_t addr, u32_t reg, u16_t value)
{
    (void)mac; (void)addr;
    writes++;
    if (bad_write) return XST_FAILURE;
    if (reg == 0x1e) selected = value;
    else if (reg == 0x1f) ext[selected] = value;
    else if (reg == 0) {
        if (value & 0x8000) resets++;
        regs[reg] = stuck_reset ? value : value & ~0x8200U;
    } else regs[reg] = value;
    return XST_SUCCESS;
}
static void usleep(unsigned int us) { assert(us == 10000); delays++; }
#include "m01_yt8521.inc"
int main(void)
{
    XEmacPs mac = {0};
    ext[0xa000] = 0x42;
    ext[0xa001] = 0x8060;
    ext[0xa003] = 0x0301;
    regs[1] = 0x24;
    regs[4] = 0x0de1;
    regs[9] = 0x0300;
    regs[0x11] = 0xac00;
    assert(m01_yt8521_speed(&mac, 1) == 1000);
    assert(ext[0xa000] == 0x40 && ext[0xa001] == 0x8160);
    assert(ext[0xa003] == 0x03dd && regs[4] == 0x0d41 && regs[9] == 0x0200);
    unsigned int saved_writes = writes;
    regs[0x11] = 0x6c00;
    assert(m01_yt8521_speed(&mac, 1) == 100 && writes == saved_writes);
    regs[0x11] = 0x2c00;
    assert(m01_yt8521_speed(&mac, 1) == 10);
    regs[0x11] = 0xec00;
    assert(m01_yt8521_speed(&mac, 1) == XST_FAILURE);
    regs[0x11] = 0x8c00; /* Half duplex is not silently claimed as full. */
    assert(m01_yt8521_speed(&mac, 1) == XST_FAILURE);
    bad_read = 1;
    assert(m01_yt8521_speed(&mac, 2) == XST_FAILURE);
    bad_read = 0; bad_write = 1;
    assert(m01_yt8521_speed(&mac, 2) == XST_FAILURE);
    bad_write = 0;
    ext[0xa001] = 0x8050; /* 2.5 V must never be rewritten to 1.8 V. */
    assert(m01_yt8521_speed(&mac, 2) == XST_FAILURE && ext[0xa001] == 0x8050);
    ext[0xa001] = 0x8061; /* Fiber mode must not be changed blindly. */
    assert(m01_yt8521_speed(&mac, 2) == XST_FAILURE);
    ext[0xa001] = 0x8060;
    stuck_reset = 1; delays = 0;
    assert(m01_yt8521_speed(&mac, 2) == XST_FAILURE && delays == 100);
    stuck_reset = 0; regs[1] = 0; delays = 0;
    assert(m01_yt8521_speed(&mac, 3) == XST_FAILURE && delays == 500);
    assert(resets == 3);
    puts("YT8521_CHECK_PASS");
    return 0;
}
