# Volatile JTAG load; never writes boot media.
if {[catch {
    if {[llength $argv] != 1} {error "usage: run_usb_probe_jtag.tcl <Vitis workspace>"}
    set workspace [file normalize [lindex $argv 0]]
    set elf "$workspace/usb_probe/build/usb_probe.elf"
    set bit "$workspace/usb_probe/_ide/bitstream/m01.bit"
    set init "$workspace/usb_probe/_ide/psinit/ps7_init.tcl"
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
    puts "USB_PROBE_JTAG_RUNNING"
    disconnect
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
