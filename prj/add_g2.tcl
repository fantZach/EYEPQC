# G2: PS HP0 DDR -> native AXI DMA -> M08 AES-GCM -> native AXI DMA -> DDR.
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 1 CONFIG.PCW_S_AXI_HP0_DATA_WIDTH 64 \
    CONFIG.PCW_USE_FABRIC_INTERRUPT 1 CONFIG.PCW_IRQ_F2P_INTR 1] $ps
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 dma_crypto]
set_property -dict [list CONFIG.c_include_sg 0 CONFIG.c_sg_length_width 23 \
    CONFIG.c_include_mm2s 1 CONFIG.c_include_s2mm 1 \
    CONFIG.c_m_axi_mm2s_data_width 64 CONFIG.c_m_axi_s2mm_data_width 64 \
    CONFIG.c_m_axis_mm2s_tdata_width 32 CONFIG.c_s_axis_s2mm_tdata_width 32 \
    CONFIG.c_mm2s_burst_size 16 CONFIG.c_s2mm_burst_size 16 \
    CONFIG.c_include_mm2s_dre 1 CONFIG.c_include_s2mm_dre 1 \
    CONFIG.c_include_s2mm_sf 1] $dma
set gcm [create_bd_cell -type module -reference aes_gcm_axis gcm_0]
set regs [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 dma_regs]
set_property CONFIG.NUM_MI 2 $regs
set memory [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 dma_memory]
set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1] $memory
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins dma_regs/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins dma_regs/M00_AXI] [get_bd_intf_pins dma_crypto/S_AXI_LITE]
connect_bd_intf_net [get_bd_intf_pins dma_regs/M01_AXI] [get_bd_intf_pins gcm_0/s_axi]
assign_bd_address -offset 0x40410000 -range 64K [get_bd_addr_segs dma_crypto/S_AXI_LITE/*]
assign_bd_address -offset 0x43C00000 -range 4K [get_bd_addr_segs gcm_0/s_axi/*]
connect_bd_intf_net [get_bd_intf_pins dma_memory/S00_AXI] [get_bd_intf_pins dma_crypto/M_AXI_MM2S]
connect_bd_intf_net [get_bd_intf_pins dma_memory/S01_AXI] [get_bd_intf_pins dma_crypto/M_AXI_S2MM]
connect_bd_intf_net [get_bd_intf_pins dma_memory/M00_AXI] [get_bd_intf_pins ps7/S_AXI_HP0]
connect_bd_intf_net [get_bd_intf_pins dma_crypto/M_AXIS_MM2S] [get_bd_intf_pins gcm_0/s_axis]
connect_bd_intf_net [get_bd_intf_pins gcm_0/m_axis] [get_bd_intf_pins dma_crypto/S_AXIS_S2MM]
set irqs [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconcat:1.0 g2_irqs]
set_property CONFIG.NUM_PORTS 3 $irqs
foreach {index pin} {0 dma_crypto/mm2s_introut 1 dma_crypto/s2mm_introut 2 gcm_0/irq} {
    connect_bd_net [get_bd_pins $pin] [get_bd_pins g2_irqs/In$index]
}
connect_bd_net [get_bd_pins g2_irqs/dout] [get_bd_pins ps7/IRQ_F2P]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins ps7/M_AXI_GP0_ACLK] [get_bd_pins ps7/S_AXI_HP0_ACLK]
foreach cell {dma_regs dma_memory dma_crypto gcm_0} {
    foreach pin [get_bd_pins -of_objects [get_bd_cells $cell] -filter {TYPE == clk && DIR == I}] {
        connect_bd_net [get_bd_pins ps7/FCLK_CLK0] $pin
    }
    foreach pin [get_bd_pins -of_objects [get_bd_cells $cell] -filter {TYPE == rst && DIR == I}] {
        connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] $pin
    }
}
assign_bd_address
