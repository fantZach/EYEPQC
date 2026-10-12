# Verify the just-built M01 implementation without opening hardware.
if {$argc != 2} {error "usage: check_g0_implemented.tcl <project.xpr> <evidence.txt>"}
set xpr [file normalize [lindex $argv 0]]
set evidence [file normalize [lindex $argv 1]]
open_project $xpr
open_run impl_1
set led [get_ports -quiet led]
if {[llength $led] != 1} {error "Expected exactly one implemented led port"}
set pin [get_property PACKAGE_PIN $led]
set iostandard [get_property IOSTANDARD $led]
if {$pin ne "H15" || $iostandard ne "LVCMOS33"} {
    error "Implemented LED constraint mismatch: PACKAGE_PIN=$pin IOSTANDARD=$iostandard"
}
set hb_pin [get_pins -hierarchical -quiet -filter {NAME =~ *heartbeat_0/clk}]
if {[llength $hb_pin] != 1} {error "Could not identify implemented heartbeat_0/clk"}
set clocks [get_clocks -quiet -of_objects $hb_pin]
if {[llength $clocks] != 1} {error "Could not identify heartbeat clock"}
set period [get_property PERIOD $clocks]
if {abs($period - 10.0) > 0.01} {error "Heartbeat clock period is not 10 ns: $period"}
report_io -file $evidence
report_clocks -file "${evidence}.clocks.txt"
set fd [open "${evidence}.verified.txt" w]
puts $fd "G0_IMPLEMENTED_OK led_PACKAGE_PIN=$pin led_IOSTANDARD=$iostandard heartbeat_clock_period_ns=$period"
close $fd
puts "G0_IMPLEMENTED_OK led_PACKAGE_PIN=$pin led_IOSTANDARD=$iostandard heartbeat_clock_period_ns=$period"
close_project
