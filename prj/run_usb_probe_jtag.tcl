# Volatile JTAG load; never writes boot media.
if {[catch {
    if {[llength $argv] < 1 || [llength $argv] > 2} {error "usage: run_usb_probe_jtag.tcl <Vitis workspace> ?application?"}
    set workspace [file normalize [lindex $argv 0]]
    set app [expr {[llength $argv] == 2 ? [lindex $argv 1] : "usb_probe"}]
    if {$app ni {usb_probe g4_usb g5_usb g6_usb}} {error "Unsupported application: $app"}
    set elf "$workspace/$app/build/$app.elf"
    set bit "$workspace/$app/_ide/bitstream/m01.bit"
    set init "$workspace/$app/_ide/psinit/ps7_init.tcl"
    foreach path [list $elf $bit $init] {
        if {![file isfile $path]} {error "Missing USB probe artifact: $path"}
    }
    connect -url tcp:127.0.0.1:3121
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
    puts "USB_JTAG_RUNNING $app"
    disconnect
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
