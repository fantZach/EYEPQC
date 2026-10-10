# Temporary volatile KX41 load. No persistent storage is written.
if {[catch {
if {[llength $argv] != 1} {error "usage: load_keccak_sponge_x4.tcl firmware_directory"}
set root [file normalize [lindex $argv 0]]
connect -url tcp:127.0.0.1:3121
targets -set -filter {name == "APU"}
rst -system -stop
targets -set -filter {name =~ "*Cortex-A9*#0"}
source "$root/matching_ps7_init.tcl"
ps7_init
targets -set -filter {name == "xc7z020"}
fpga -file "$root/matching_system.bit"
targets -set -filter {name =~ "*Cortex-A9*#0"}
ps7_post_config
rst -processor
dow -clear "$root/firmware/build/keccak_sponge_x4_board_bench.elf"
con
puts "KECCAK_SX4_JTAG_RUNNING"
disconnect
} message options]} {
puts stderr [dict get $options -errorinfo]
catch {disconnect}
exit 1
}
