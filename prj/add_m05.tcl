# Extend the shared PS7/DDR platform. Native simple DMA; no SG descriptors or crypto RTL yet.
set_property XPM_LIBRARIES {XPM_CDC XPM_FIFO XPM_MEMORY} [current_project]
set_property -dict [list CONFIG.PCW_USE_S_AXI_HP0 1 CONFIG.PCW_S_AXI_HP0_DATA_WIDTH 64 \
    CONFIG.PCW_USE_FABRIC_INTERRUPT 1 CONFIG.PCW_IRQ_F2P_INTR 1] $ps
add_files [file join $repo src rtl common axis_byte_packer.sv]
add_files [file join $repo src rtl common axis_capture_route.sv]
add_files -fileset constrs_1 [file join $repo board xdc m05.xdc]
set_property USED_IN_SYNTHESIS false [get_files m05.xdc]
set_property PROCESSING_ORDER EARLY [get_files m05.xdc]
add_files -fileset constrs_1 [file join $repo board xdc m05_clocks.xdc]
set_property PROCESSING_ORDER EARLY [get_files m05_clocks.xdc]
set camera [create_bd_cell -type module -reference camera_dma_top camera_0]
set_property CONFIG.INIT_FILE [file join $repo src rtl camera ov5640_jpeg.mem] $camera
foreach gpio_name {camera_gpio dma_gpio} {
    set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 $gpio_name]
    set_property -dict [list CONFIG.C_GPIO_WIDTH 32 CONFIG.C_ALL_OUTPUTS 1 \
        CONFIG.C_IS_DUAL 1 CONFIG.C_GPIO2_WIDTH 32 CONFIG.C_ALL_INPUTS_2 1] $gpio
}
set cap [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 dma_capture]
set crypto [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 dma_crypto]
foreach dma [list $cap $crypto] {
    set_property -dict [list CONFIG.c_include_sg 0 CONFIG.c_sg_length_width 23 \
        CONFIG.c_include_s2mm 1 CONFIG.c_m_axi_s2mm_data_width 64 CONFIG.c_s_axis_s2mm_tdata_width 32 \
        CONFIG.c_s2mm_burst_size 16 CONFIG.c_include_s2mm_dre 1 CONFIG.c_include_s2mm_sf 1] $dma
}
set_property CONFIG.c_include_mm2s 0 $cap
set_property -dict [list CONFIG.c_include_mm2s 1 CONFIG.c_m_axi_mm2s_data_width 64 \
    CONFIG.c_m_axis_mm2s_tdata_width 32 CONFIG.c_mm2s_burst_size 16 CONFIG.c_include_mm2s_dre 1] $crypto
set regs [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 dma_regs]
set_property CONFIG.NUM_MI 4 $regs
set memory [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 dma_memory]
set_property -dict [list CONFIG.NUM_SI 3 CONFIG.NUM_MI 1] $memory
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins dma_regs/S00_AXI]
foreach {index name port offset} {00 camera_gpio S_AXI 0x41200000 01 dma_gpio S_AXI 0x41210000 \
    02 dma_capture S_AXI_LITE 0x40400000 03 dma_crypto S_AXI_LITE 0x40410000} {
    connect_bd_intf_net [get_bd_intf_pins dma_regs/M${index}_AXI] [get_bd_intf_pins $name/$port]
    assign_bd_address -offset $offset -range 64K [get_bd_addr_segs $name/$port/*]
}
foreach {index port} {00 dma_capture/M_AXI_S2MM 01 dma_crypto/M_AXI_S2MM 02 dma_crypto/M_AXI_MM2S} {
    connect_bd_intf_net [get_bd_intf_pins dma_memory/S${index}_AXI] [get_bd_intf_pins $port]
}
connect_bd_intf_net [get_bd_intf_pins dma_memory/M00_AXI] [get_bd_intf_pins ps7/S_AXI_HP0]
connect_bd_intf_net [get_bd_intf_pins dma_crypto/M_AXIS_MM2S] [get_bd_intf_pins camera_0/S_TEST_AXIS]
connect_bd_intf_net [get_bd_intf_pins camera_0/M_CAPTURE_AXIS] [get_bd_intf_pins dma_capture/S_AXIS_S2MM]
connect_bd_intf_net [get_bd_intf_pins camera_0/M_CRYPTO_AXIS] [get_bd_intf_pins dma_crypto/S_AXIS_S2MM]
connect_bd_net [get_bd_pins camera_gpio/gpio_io_o] [get_bd_pins camera_0/camera_cfg]
connect_bd_net [get_bd_pins camera_0/camera_status] [get_bd_pins camera_gpio/gpio2_io_i]
connect_bd_net [get_bd_pins dma_gpio/gpio_io_o] [get_bd_pins camera_0/dma_cfg]
connect_bd_net [get_bd_pins camera_0/dma_status] [get_bd_pins dma_gpio/gpio2_io_i]
set irqs [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconcat:1.0 dma_irqs]
set_property CONFIG.NUM_PORTS 3 $irqs
foreach {index pin} {0 dma_capture/s2mm_introut 1 dma_crypto/mm2s_introut 2 dma_crypto/s2mm_introut} {
    connect_bd_net [get_bd_pins $pin] [get_bd_pins dma_irqs/In$index]
}
connect_bd_net [get_bd_pins dma_irqs/dout] [get_bd_pins ps7/IRQ_F2P]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins ps7/M_AXI_GP0_ACLK] [get_bd_pins ps7/S_AXI_HP0_ACLK]
foreach cell {dma_regs dma_memory camera_gpio dma_gpio dma_capture dma_crypto camera_0} {
    foreach pin [get_bd_pins -of_objects [get_bd_cells $cell] -filter {TYPE == clk && DIR == I}] {
        if {$pin ne [get_bd_pins camera_0/cam_pclk]} {connect_bd_net [get_bd_pins ps7/FCLK_CLK0] $pin}
    }
    foreach pin [get_bd_pins -of_objects [get_bd_cells $cell] -filter {TYPE == rst && DIR == I}] {
        connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] $pin
    }
}
foreach pin {cam_scl cam_sda cam_resetn cam_pwdn cam_pclk cam_href cam_vsync cam_data} {
    make_bd_pins_external [get_bd_pins camera_0/$pin]
    set_property name $pin [get_bd_ports ${pin}_0]
}
assign_bd_address
