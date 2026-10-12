# Offline synthesis only; no BD, bitstream, JTAG or board writes.
set repo [file normalize [file join [file dirname [info script]] .. ..]]
if {![info exists check_top]} {set check_top ov5640_ctrl}
if {![info exists check_clock]} {set check_clock clk}
if {![info exists check_period]} {set check_period 10}
if {![info exists check_ooc]} {set check_ooc 0}
if {[llength $argv] != 1} {error "Expected one fresh output directory"}
set out [file normalize [lindex $argv 0]]
if {[file exists $out]} {error "Output already exists: $out"}
cd $repo
create_project ${check_top}_synth $out -part xc7z020clg400-2
read_verilog -sv [glob [file join $repo board src rtl camera *.sv]]
# Include native I/O buffers: OOC mode converts open-drain tristates to logic.
if {$check_ooc} {
    synth_design -top $check_top -mode out_of_context
} else {
    synth_design -top $check_top
}
create_clock -name $check_clock -period $check_period [get_ports $check_clock]
report_utilization -file [file join $out utilization.txt]
report_timing_summary -file [file join $out timing.txt]
if {$check_top eq "ov5640_ctrl"} {
    write_checkpoint [file join $out m02_ooc.dcp]
    puts "M02_SYNTH_OK (synthesis only; no board acceptance or implemented timing)"
} else {
    write_checkpoint [file join $out ${check_top}.dcp]
    puts "M03_SYNTH_OK top=$check_top (synthesis only; no board acceptance or implemented timing)"
}
