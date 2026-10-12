# Isolated PS+PL Keccak experiment. This intentionally mirrors only the
# confirmed PS7 configuration in build_m01.tcl and never edits that project.
set repo [file normalize [file join [file dirname [info script]] .. ..]]
if {[llength $argv] != 1} {error "usage: keccak_system.tcl <fresh_output_directory>"}
set out [file normalize [lindex $argv 0]]
if {[file exists $out]} {error "Output already exists: $out. Use a fresh directory."}
if {[llength [get_parts -quiet xc7z020clg400-2]] != 1} {
    error "Missing Zynq-7020 target xc7z020clg400-2"
}
file mkdir $out
create_project keccak_experiment $out -part xc7z020clg400-2
set_property target_language Verilog [current_project]
add_files [file join $repo board src rtl crypto keccak_round.sv]
add_files [file join $repo board src rtl crypto keccak_f1600.sv]
add_files [file join $repo board src rtl crypto keccak_axi_lite.sv]
create_bd_design system
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7]
# These are the same board-confirmed PS parameters used by build_m01.tcl.
set_property -dict [list \
    CONFIG.PCW_PACKAGE_NAME {clg400} \
    CONFIG.PCW_CRYSTAL_PERIPHERAL_FREQMHZ {33.333333} \
    CONFIG.PCW_APU_PERIPHERAL_FREQMHZ {666.666667} \
    CONFIG.PCW_PRESET_BANK0_VOLTAGE {LVCMOS 3.3V} \
    CONFIG.PCW_PRESET_BANK1_VOLTAGE {LVCMOS 1.8V} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
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
    CONFIG.PCW_USB0_PERIPHERAL_ENABLE {1} \
    CONFIG.PCW_USB0_USB0_IO {MIO 28 .. 39} \
    CONFIG.PCW_USB0_RESET_ENABLE {1} \
    CONFIG.PCW_USB0_RESET_IO {MIO 9} \
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
set conv [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_protocol_converter:2.1 axi_convert]
set_property -dict [list CONFIG.SI_PROTOCOL {AXI3} CONFIG.MI_PROTOCOL {AXI4LITE}] $conv
set keccak [create_bd_cell -type module -reference keccak_axi_lite keccak_0]
set rst [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 reset_0]
set_property CONFIG.C_AUX_RESET_HIGH 1 $rst
set one [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 one]
set zero [create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconstant:1.0 zero]
set_property CONFIG.CONST_VAL 1 $one
set_property CONFIG.CONST_VAL 0 $zero
connect_bd_intf_net [get_bd_intf_pins ps7/M_AXI_GP0] [get_bd_intf_pins axi_convert/S_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_convert/M_AXI] [get_bd_intf_pins keccak_0/s_axi]
connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins ps7/M_AXI_GP0_ACLK] \
    [get_bd_pins axi_convert/aclk] [get_bd_pins keccak_0/s_axi_aclk] \
    [get_bd_pins reset_0/slowest_sync_clk]
connect_bd_net [get_bd_pins ps7/FCLK_RESET0_N] [get_bd_pins reset_0/ext_reset_in]
connect_bd_net [get_bd_pins one/dout] [get_bd_pins reset_0/dcm_locked]
connect_bd_net [get_bd_pins zero/dout] [get_bd_pins reset_0/aux_reset_in] [get_bd_pins reset_0/mb_debug_sys_rst]
connect_bd_net [get_bd_pins reset_0/peripheral_aresetn] \
    [get_bd_pins axi_convert/aresetn] [get_bd_pins keccak_0/s_axi_aresetn]
assign_bd_address -offset 0x43C10000 -range 4K [get_bd_addr_segs keccak_0/s_axi/reg0]
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
add_files [make_wrapper -files [get_files system.bd] -top]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
report_ip_status -file [file join $out ip_status.txt]
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property STATUS [get_runs impl_1]] ne "write_bitstream Complete!"} {
    error "Implementation failed: [get_property STATUS [get_runs impl_1]]"
}
open_run impl_1
report_timing_summary -file [file join $out timing.txt]
report_utilization -file [file join $out utilization.txt]
report_drc -file [file join $out drc.txt]
set critical [get_drc_violations -quiet -filter {SEVERITY == Critical_Warning || SEVERITY == Error}]
if {[llength $critical] != 0} {error "Critical DRC/Error violations present: $critical"}
foreach delay_type {max min} {
    set paths [get_timing_paths -delay_type $delay_type -max_paths 1]
    if {[llength $paths] == 0 || [get_property SLACK $paths] < 0} {
        error "Missing or negative $delay_type timing slack"
    }
}
write_hw_platform -fixed -include_bit -file [file join $out keccak_experiment.xsa]
puts "KECCAK_SYSTEM_IMPLEMENTED $out/keccak_experiment.xsa (offline only; board not accessed)"
exit
