/* CF7020B copper PHY; inserted into the generated AMD BSP, never its install. */
#define M01_YT_TX_DELAY 13U /* 13 * 150 ps = 1.95 ns; board calibration knob. */

static int m01_phy_modify(XEmacPs *mac, u32_t addr, u32_t reg,
                          u16_t mask, u16_t bits)
{
    u16_t value, check;
    if (XEmacPs_PhyRead(mac, addr, reg, &value) != XST_SUCCESS ||
        XEmacPs_PhyWrite(mac, addr, reg, (value & ~mask) | bits) != XST_SUCCESS ||
        XEmacPs_PhyRead(mac, addr, reg, &check) != XST_SUCCESS ||
        (check & mask) != bits) return XST_FAILURE;
    return XST_SUCCESS;
}

static u32_t m01_yt8521_speed(XEmacPs *mac, u32_t addr)
{
    static u32_t configured;
    u16_t cfg, status = 0;
    unsigned int n = 0;
    const char *stage = "copper MDIO";
    if (configured & (1U << addr)) goto negotiated;
    /* Select copper registers; preserve every unrelated/voltage strap bit. */
    if (XEmacPs_PhyWrite(mac, addr, 0x1e, 0xa000) != XST_SUCCESS ||
        m01_phy_modify(mac, addr, 0x1f, 2, 0) != XST_SUCCESS ||
        XEmacPs_PhyWrite(mac, addr, 0x1e, 0xa001) != XST_SUCCESS ||
        XEmacPs_PhyRead(mac, addr, 0x1f, &cfg) != XST_SUCCESS) goto fail;
    xil_printf("M01 PHY YT8521 addr=%u chip_cfg=%04x\r\n", addr, cfg);
    /* ponytail: only this board's UTP/RGMII mode; other media belong in M11. */
    stage = "mode/voltage";
    if ((cfg & 7U) != 0 || (cfg & 0x60U) != 0x60U) goto fail;
    stage = "reset";
    if (XEmacPs_PhyWrite(mac, addr, 0, 0x8000) != XST_SUCCESS) goto fail;
    for (n = 0; n < 100; n++) {
        if (XEmacPs_PhyRead(mac, addr, 0, &status) != XST_SUCCESS) goto fail;
        if (!(status & 0x8000U)) break;
        usleep(10000);
    }
    if (n == 100) goto fail;
    /* RX base delay 2 ns, no extra RX delay; TX delay at all copper speeds. */
    stage = "RGMII/advertisement";
    if (XEmacPs_PhyWrite(mac, addr, 0x1e, 0xa001) != XST_SUCCESS ||
        m01_phy_modify(mac, addr, 0x1f, 0x100, 0x100) != XST_SUCCESS ||
        XEmacPs_PhyWrite(mac, addr, 0x1e, 0xa003) != XST_SUCCESS ||
        m01_phy_modify(mac, addr, 0x1f, 0x3cff,
                       (M01_YT_TX_DELAY << 4) | M01_YT_TX_DELAY) != XST_SUCCESS ||
        /* Advertise full duplex only: GEM's native path assumes full duplex. */
        m01_phy_modify(mac, addr, 4, 0x03e0, 0x0140) != XST_SUCCESS ||
        m01_phy_modify(mac, addr, 9, 0x0300, 0x0200) != XST_SUCCESS ||
        XEmacPs_PhyRead(mac, addr, 0, &status) != XST_SUCCESS ||
        XEmacPs_PhyWrite(mac, addr, 0, (status & ~0x1e00U) | 0x1200U) != XST_SUCCESS)
        goto fail; /* BMCR restart is self-clearing, not a readback-equality bit. */
    configured |= 1U << addr;
    stage = "autoneg timeout";
    for (n = 0; n < 500; n++) {
        if (XEmacPs_PhyRead(mac, addr, 1, &status) != XST_SUCCESS) goto fail;
        if ((status & 0x24U) == 0x24U) break;
        usleep(10000);
    }
    if (n == 500) goto fail;
negotiated: /* Native recovery calls only after link+autoneg; do not restart it. */
    stage = "resolved full-duplex link";
    if (XEmacPs_PhyRead(mac, addr, 0x11, &status) != XST_SUCCESS ||
        (status & 0x2c00U) != 0x2c00U) goto fail;
    xil_printf("M01 PHY status=%04x tx_delay_step=%u\r\n", status, M01_YT_TX_DELAY);
    switch (status & 0xc000U) {
        case 0x8000: return 1000;
        case 0x4000: return 100;
        case 0x0000: return 10;
        default: break;
    }
fail:
    xil_printf("M01 PHY FAIL stage=%s status=%04x attempts=%u\r\n", stage, status, n);
    return XST_FAILURE;
}
