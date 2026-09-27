# Offline synthesis only; no BD, bitstream, JTAG or board writes.
set repo [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv] != 1} {error "Expected one fresh output directory"}
set out [file normalize [lindex $argv 0]]
if {[file exists $out]} {error "Output already exists: $out"}
cd $repo
create_project m02_ooc $out -part xc7z020clg400-2
read_verilog -sv [glob [file join $repo src rtl camera *.sv]]
# Include native I/O buffers: OOC mode converts open-drain tristates to logic.
synth_design -top ov5640_ctrl
create_clock -name clk -period 10 [get_ports clk]
report_utilization -file [file join $out utilization.txt]
report_timing_summary -file [file join $out timing.txt]
write_checkpoint [file join $out m02_ooc.dcp]
puts "M02_SYNTH_OK (synthesis only; no board acceptance or implemented timing)"
