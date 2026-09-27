# Vivado 2026.1: batch -source prj/build_m01.tcl [-tclargs output_directory]
# Hynix H5TC4G63EFR-RDA, conservative DDR3L-1066 timings (datasheet Rev. 1.3).
# User confirmed two x16 chips: 32-bit / 1 GiB. Core V2.5 schematic uses 1.35 V.
# Confirm physical revision/PHY and connect UART before board validation.
set repo [file normalize [file join [file dirname [info script]] ..]]
if {![info exists aes_mvp]} {set aes_mvp 0}
set out [file join $repo build vivado m01]
if {[llength $argv] == 1} {set out [file normalize [lindex $argv 0]]}
if {[llength $argv] > 1} {error "Expected at most one output directory"}
if {[file exists $out]} {error "Output already exists: $out. Use a fresh directory."}
if {[llength [get_parts -quiet xc7z020clg400-2]] != 1} {
    error "Install Vivado Zynq-7000 device support: xc7z020clg400-2 is missing"
}
create_project m01 $out -part xc7z020clg400-2
set_property target_language Verilog [current_project]
add_files [file join $repo src rtl common heartbeat.sv]
if {$aes_mvp} {
    add_files [glob [file join $repo src rtl crypto secworks_aes *.v]]
    add_files [file join $repo src rtl crypto aes_axi_lite.sv]
}
add_files -fileset constrs_1 [file join $repo board xdc m01.xdc]
create_bd_design system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
# Only user parameters, not the 2020.2 generated/derived property dump.
set_property -dict [list \
    CONFIG.PCW_PACKAGE_NAME {clg400} \
    CONFIG.PCW_CRYSTAL_PERIPHERAL_FREQMHZ {33.333333} \
    CONFIG.PCW_APU_PERIPHERAL_FREQMHZ {666.666667} \
    CONFIG.PCW_PRESET_BANK0_VOLTAGE {LVCMOS 3.3V} \
    CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
    CONFIG.PCW_USE_M_AXI_GP0 $aes_mvp \
    CONFIG.PCW_UART0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_UART0_UART0_IO {MIO 14 .. 15} \
    CONFIG.PCW_UART0_BAUD_RATE {115200} \
    CONFIG.PCW_UART_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_SD0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_SD0_SD0_IO {MIO 40 .. 45} \
    CONFIG.PCW_SD0_GRP_CD_ENABLE {1} \
    CONFIG.PCW_SD0_GRP_CD_IO {MIO 10} \
    CONFIG.PCW_SD0_GRP_WP_ENABLE {0} \
    CONFIG.PCW_SD0_GRP_POW_ENABLE {0} \
    CONFIG.PCW_ENET0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_ENET0_ENET0_IO {MIO 16 .. 27} \
    CONFIG.PCW_ENET0_GRP_MDIO_ENABLE {1} \
    CONFIG.PCW_ENET0_GRP_MDIO_IO {MIO 52 .. 53} \
    CONFIG.PCW_ENET0_PERIPHERAL_FREQMHZ {1000 Mbps} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_EN_RST0_PORT {1} \
    CONFIG.PCW_FPGA_FCLK0_ENABLE {1} \
    CONFIG.PCW_FCLK_CLK0_BUF {TRUE} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
    CONFIG.PCW_UIPARAM_DDR_ENABLE {1} \
    CONFIG.PCW_UIPARAM_DDR_MEMORY_TYPE {DDR 3 (Low Voltage)} \
    CONFIG.PCW_UIPARAM_DDR_PARTNO {Custom} \
    CONFIG.PCW_UIPARAM_DDR_BUS_WIDTH {32 Bit} \
    CONFIG.PCW_UIPARAM_DDR_FREQ_MHZ {533.333333} \
    CONFIG.PCW_UIPARAM_DDR_DEVICE_CAPACITY {4096 MBits} \
    CONFIG.PCW_UIPARAM_DDR_DRAM_WIDTH {16 Bits} \
    CONFIG.PCW_UIPARAM_DDR_BANK_ADDR_COUNT {3} \
    CONFIG.PCW_UIPARAM_DDR_ROW_ADDR_COUNT {15} \
    CONFIG.PCW_UIPARAM_DDR_COL_ADDR_COUNT {10} \
    CONFIG.PCW_UIPARAM_DDR_SPEED_BIN {DDR3_1066G} \
    CONFIG.PCW_UIPARAM_DDR_CL {8} \
    CONFIG.PCW_UIPARAM_DDR_CWL {6} \
    CONFIG.PCW_UIPARAM_DDR_T_FAW {50.0} \
    CONFIG.PCW_UIPARAM_DDR_T_RAS_MIN {36.0} \
    CONFIG.PCW_UIPARAM_DDR_T_RC {51.0} \
    CONFIG.PCW_UIPARAM_DDR_T_RCD {8} \
    CONFIG.PCW_UIPARAM_DDR_T_RP {8} \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_DATA_EYE {1} \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_READ_GATE {1} \
    CONFIG.PCW_UIPARAM_DDR_TRAIN_WRITE_LEVEL {1} \
] $ps
for {set i 0} {$i < 4} {incr i} {
    set_property CONFIG.PCW_UIPARAM_DDR_BOARD_DELAY$i 0.25 $ps
    set_property CONFIG.PCW_UIPARAM_DDR_DQS_TO_CLK_DELAY_$i 0.0 $ps
}
make_bd_intf_pins_external [get_bd_intf_pins ps7/DDR]
make_bd_intf_pins_external [get_bd_intf_pins ps7/FIXED_IO]
set_property name DDR [get_bd_intf_ports DDR_0]
set_property name FIXED_IO [get_bd_intf_ports FIXED_IO_0]
create_bd_cell -type module -reference heartbeat heartbeat_0
set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset_0]
# FCLK_RESET0_N is active-low; the tied-zero auxiliary reset must be active-high.
set_property -dict [list CONFIG.C_EXT_RESET_HIGH 0 CONFIG.C_AUX_RESET_HIGH 1] $rst
set one [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 one]
set zero [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 zero]
set_property CONFIG.CONST_VAL 0 $zero
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins reset_0/slowest_sync_clk] [get_bd_pins heartbeat_0/clk]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins reset_0/ext_reset_in]
connect_bd_net [get_bd_pins one/dout] [get_bd_pins reset_0/dcm_locked]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins reset_0/aux_reset_in] [get_bd_pins reset_0/mb_debug_sys_rst]
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] [get_bd_pins heartbeat_0/resetn]
create_bd_port -dir O led
connect_bd_net [get_bd_pins heartbeat_0/led] [get_bd_ports led]
if {$aes_mvp} {
    create_bd_cell -type module -reference aes_axi_lite aes_0
    set conv [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_protocol_converter:2.1 axi_convert]
    set_property -dict [list CONFIG.SI_PROTOCOL {AXI3} CONFIG.MI_PROTOCOL {AXI4LITE}] $conv
    connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_convert/S_AXI]
    connect_bd_intf_net [get_bd_intf_pins axi_convert/M_AXI] [get_bd_intf_pins aes_0/s_axi]
    connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins ps7/M_AXI_GP0_ACLK] \
        [get_bd_pins axi_convert/aclk] [get_bd_pins aes_0/s_axi_aclk]
    connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] \
        [get_bd_pins axi_convert/aresetn] [get_bd_pins aes_0/s_axi_aresetn]
    assign_bd_address -offset 0x43C00000 -range 4K [get_bd_addr_segs aes_0/s_axi/reg0]
}
validate_bd_design
if {[get_property CONFIG.C_EXT_RESET_HIGH $rst] != 0 ||
    [get_property CONFIG.C_AUX_RESET_HIGH $rst] != 1} {
    error "Reset polarity changed: tied-zero aux_reset_in must not assert reset"
}
if {[get_property CONFIG.C_EXT_RESET_HIGH $rst] != 0} {
    error "PS reset is active-low; proc_sys_reset polarity propagation failed"
}
save_bd_design
# Catch clock preset changes instead of silently retaining a wrong heartbeat/tick rate.
foreach {property expected} {
    CONFIG.PCW_ACT_APU_PERIPHERAL_FREQMHZ 666.666667
    CONFIG.PCW_ACT_FPGA0_PERIPHERAL_FREQMHZ 100.0
    CONFIG.PCW_ACT_ENET0_PERIPHERAL_FREQMHZ 125.0
    CONFIG.PCW_UIPARAM_ACT_DDR_FREQ_MHZ 533.333333
} {
    set actual [get_property $property $ps]
    if {abs($actual - $expected) > 0.01} {error "Unexpected $property: $actual"}
    puts "M01_CLOCK $property=$actual MHz"
}
generate_target all [get_files system.bd]
add_files [make_wrapper -files [get_files system.bd] -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
report_ip_status -file [file join $out ip_status.txt]
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {
    error "Implementation did not complete: [get_property STATUS [get_runs impl_1]]"
}
open_run impl_1
report_timing_summary -file [file join $out timing.txt]
report_utilization -file [file join $out utilization.txt]
report_drc -file [file join $out drc.txt]
foreach delay_type {max min} {
    if {[get_property SLACK [get_timing_paths -delay_type $delay_type -max_paths 1]] < 0} {
        error "Negative $delay_type timing slack"
    }
}
write_hw_platform -fixed -include_bit -file [file join $out m01.xsa]
puts "M01_BUILD_OK $out/m01.xsa (offline only; board acceptance still pending)"
