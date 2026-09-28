# Strictly one XSDB process at a time. Only volatile hardware and ELF-owned RAM.
if {[catch {
    if {[llength $argv] != 11} {error "usage: workspace boot command count cache mailbox frames reply payload timeout_ms sensor_cfg"}
    lassign $argv workspace boot command count cache address frames reply payload timeout sensor_cfg
    set workspace [file normalize $workspace]
    foreach var {boot command count cache address frames timeout sensor_cfg} {set $var [expr {[set $var]}]}
    if {$address < 0x100000 || $address + 128 > 0x40000000 || $address % 64 ||
        $frames < 0x100000 || $frames + 131200 > 0x40000000 || $frames % 64 ||
        $boot ni {0 1} || $command ni {1 2 3} || $cache ni {0 1} || $count < 1 || $count > 10000} {
        error "Invalid owned DDR mailbox/arguments"
    }
    if {[file exists $reply] || [file exists $payload]} {error "Refusing to overwrite capture"}
    connect -url tcp:127.0.0.1:3121
    if {$boot} {
        targets -set -filter {name == "APU"}
        rst -system -stop
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        source "$workspace/camera_dma/_ide/psinit/ps7_init.tcl"
        ps7_init
        targets -set -filter {name == "xc7z020"}
        fpga -file "$workspace/camera_dma/_ide/bitstream/m01.bit"
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        ps7_post_config
        rst -processor
        dow -clear "$workspace/camera_dma/build/camera_dma.elf"
        con
        puts "M05_BOOT_OK"
    }
    targets -set -filter {name == "APU"}
    set start [clock milliseconds]
    while {[lindex [mrd -address-space AP0 -value $address] 0] != 0x35414d44} {
        if {[clock milliseconds] - $start > 10000} {error "M05 boot timeout"}
        after 100
    }
    set state [lindex [mrd -address-space AP0 -value [expr {$address+4}]] 0]
    if {$state == 1} {error "M05 job already active"}
    mwr -address-space AP0 [expr {$address+8}] $command
    mwr -address-space AP0 [expr {$address+12}] $count
    mwr -address-space AP0 [expr {$address+16}] $cache
    mwr -address-space AP0 [expr {$address+124}] $sensor_cfg
    mwr -address-space AP0 [expr {$address+4}] 1
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$address+4}]] 0]
        if {$state == 2 || $state == 3} {break}
        if {[clock milliseconds] - $start > $timeout} {error "M05 command timeout"}
        after 100
    }
    mrd -address-space AP0 -bin -file $reply $address 32
    if {$state == 2 && $command == 2} {
        set data [lindex [mrd -address-space AP0 -value [expr {$address+64}]] 0]
        set length [lindex [mrd -address-space AP0 -value [expr {$address+68}]] 0]
        if {($data != $frames && $data != $frames+65600) || $length < 4 || $length > 65536} {
            error "Invalid completed frame address/length"
        }
        mrd -address-space AP0 -bin -file $payload $data [expr {($length+3)/4}]
    }
    disconnect
    puts "M05_JOB_DONE state=$state command=$command (no storage/network writes)"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
