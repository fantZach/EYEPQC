set repo [file normalize [file join [file dirname [info script]] .. ..]]
if {[llength $argv] != 1} {error "usage: check_m07.tcl fresh-output-directory"}
set out [file normalize [lindex $argv 0]]
if {[file exists $out]} {error "Use a fresh output directory: $out"}
file mkdir $out
if {[llength [get_parts -quiet xc7z020clg400-2]] != 1} {error "Zynq-7000 part missing"}
read_verilog -sv [file join $repo board src rtl crypto gf128_mul.sv]
read_verilog -sv [file join $repo board src rtl crypto ghash.sv]
synth_design -top ghash -part xc7z020clg400-2 -mode out_of_context
create_clock -name clk -period 10 [get_ports clk]
report_utilization -file [file join $out utilization.txt]
report_timing_summary -file [file join $out timing.txt]
write_checkpoint [file join $out ghash.dcp]
puts "M07_SYNTH_OK $out (100 MHz OOC estimate, not board timing)"
