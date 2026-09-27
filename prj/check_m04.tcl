# Independent native XPM synthesis; no board download or camera snapshot bypass.
set repo [file normalize [file join [file dirname [info script]] ..]]
if {[llength $argv] != 1} {error "Expected one fresh output directory"}
set out [file normalize [lindex $argv 0]]
if {[file exists $out]} {error "Output already exists: $out"}
cd $repo
create_project m04_synth $out -part xc7z020clg400-2
set_property XPM_LIBRARIES {XPM_FIFO XPM_CDC XPM_MEMORY} [current_project]
read_verilog -sv [list [file join $repo src rtl common axis_byte_packer.sv] \
    [file join $repo src rtl camera camera_axis_bridge.sv]]
read_xdc [file join $repo prj m04_ooc.xdc]
set_property PROCESSING_ORDER EARLY [get_files m04_ooc.xdc]
synth_design -top camera_axis_bridge -mode out_of_context
report_utilization -file [file join $out utilization.txt]
report_timing_summary -file [file join $out timing.txt]
report_cdc -file [file join $out cdc.txt]
report_bus_skew -file [file join $out bus_skew.txt]
write_checkpoint [file join $out camera_axis_bridge.dcp]
puts "M04_SYNTH_OK (OOC synthesis only; not implemented timing or board acceptance)"
