# Run the normal M02 build with explicit placement and selectable route directives.
# This changes implementation strategy only; RTL, XDC, and probe behavior remain pinned.
if {[llength $argv] < 1 || [llength $argv] > 2} {
    error "usage: build_m02_timing_explore.tcl <fresh output directory> ?Explore|AggressiveExplore?"
}
set output_directory [lindex $argv 0]
set route_directive Explore
if {[llength $argv] == 2} {set route_directive [lindex $argv 1]}
if {$route_directive ni {Explore AggressiveExplore}} {
    error "Unsupported route directive: $route_directive"
}
set argv [list $output_directory]
rename ::launch_runs ::launch_runs_default
proc ::launch_runs {args} {
    global route_directive
    if {[lindex $args 0] eq "impl_1"} {
        set run [get_runs impl_1]
        set_property STEPS.PLACE_DESIGN.ARGS.DIRECTIVE Explore $run
        set_property STEPS.ROUTE_DESIGN.ARGS.DIRECTIVE $route_directive $run
        puts "M02_IMPL_DIRECTIVES place=Explore route=$route_directive"
    }
    return [uplevel 1 [linsert $args 0 ::launch_runs_default]]
}
source [file join [file dirname [info script]] build_m02.tcl]
