# Read-only post-implementation reports; no IO timing assumptions are added here.
if {[llength $argv] != 1} {error "usage: report_m05.tcl hardware-directory"}
set hw [file normalize [lindex $argv 0]]
open_checkpoint [file join $hw m01.runs impl_1 system_wrapper_routed.dcp]
foreach synchronizer {camera_reset axis_reset_cdc} {
    set cells [get_cells -hier -filter "NAME =~ *$synchronizer*"]
    if {[llength $cells] < 2} {error "Missing native reset synchronizer: $synchronizer"}
    puts "M05_RESET_CELLS $synchronizer=[llength $cells]"
}
report_cdc -details -file [file join $hw cdc.txt]
report_bus_skew -file [file join $hw bus_skew.txt]
report_clock_interaction -file [file join $hw clock_interaction.txt]
report_timing_summary -report_unconstrained -file [file join $hw timing_unconstrained.txt]
foreach {filename violation} {cdc.txt {CDC-[0-9]+\s+Critical\s+[1-9]} bus_skew.txt {Slack \(VIOLATED\)}} {
    set handle [open [file join $hw $filename] r]
    set report [read $handle]
    close $handle
    if {[regexp $violation $report]} {error "Unresolved violation in $filename"}
}
puts "M05_REPORT_OK (external DVP input delay characterization still pending)"
