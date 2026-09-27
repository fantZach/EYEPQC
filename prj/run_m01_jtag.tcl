# Volatile JTAG only: no SD/QSPI/eMMC writes. Run capture_uart.ps1 first.
if {[catch {
if {[llength $argv] != 1} { error "usage: xsdb run_m01_jtag.tcl <Vitis workspace>" }
set workspace [file normalize [lindex $argv 0]]
set elf "$workspace/m01/build/m01.elf"
set bit "$workspace/m01/_ide/bitstream/m01.bit"
set init "$workspace/m01/_ide/psinit/ps7_init.tcl"
foreach path [list $elf $bit $init "$workspace/build_manifest.json"] {
    if {![file isfile $path]} { error "Missing built artifact: $path" }
}
connect -url tcp:127.0.0.1:3121
puts [targets]
targets -set -filter {name == "xc7z020"}
targets -set -filter {name == "APU"}
rst -system -stop
targets -set -filter {name =~ "*Cortex-A9*#0"}
source $init
puts "M01_JTAG_PS_INIT"
ps7_init
targets -set -filter {name == "xc7z020"}
fpga -file $bit
puts "M01_JTAG_FPGA_OK"
targets -set -filter {name =~ "*Cortex-A9*#0"}
ps7_post_config
rst -processor
dow $elf
con
puts "M01_JTAG_RUNNING"
disconnect
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
