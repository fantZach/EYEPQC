# Temporary G0 load for the coordinated DDR/timer/LED probe. Volatile JTAG only.
if {[catch {
    if {[llength $argv] != 1} {error "usage: xsdb run_g0_jtag.tcl <G0 software workspace>"}
    set workspace [file normalize [lindex $argv 0]]
    set app [file join $workspace g0_startup]
    set elf [file join $app build g0_startup.elf]
    set bit [file join $app _ide bitstream m01.bit]
    set init [file join $app _ide psinit ps7_init.tcl]
    foreach path [list $elf $bit $init [file join $workspace g0_manifest.json]] {
        if {![file isfile $path]} {error "Missing preflighted G0 artifact: $path"}
    }
    connect -url tcp:127.0.0.1:3121
    puts [targets]
    targets -set -filter {name == "xc7z020"}
    targets -set -filter {name == "APU"}
    rst -system -stop
    targets -set -filter {name =~ "*Cortex-A9*#0"}
    source $init
    ps7_init
    targets -set -filter {name == "xc7z020"}
    fpga -file $bit
    targets -set -filter {name =~ "*Cortex-A9*#0"}
    ps7_post_config
    rst -processor
    dow -clear $elf
    con
    puts "G0_JTAG_RUNNING"
    disconnect
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
