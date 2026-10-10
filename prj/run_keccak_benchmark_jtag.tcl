# Volatile experimental JTAG load; no SD/Flash writes.
if {[catch {
if {[llength $argv] != 2} {error "usage: load_keccak.tcl firmware_directory variant"}
set root [file normalize [lindex $argv 0]]
set variant [lindex $argv 1]
if {$variant ni {firmware_sw firmware_hw}} {error "invalid variant"}
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
dow -clear "$root/$variant/build/$variant.elf"
con
puts "KECCAK_JTAG_RUNNING $variant"
disconnect
} message options]} {
puts stderr [dict get $options -errorinfo]
catch {disconnect}
exit 1
}
