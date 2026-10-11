# Volatile M10 JTAG mailbox; source and addresses are checked by the host manifest.
if {[catch {
    if {[llength $argv] != 10} {
        error "usage: workspace boot command mailbox sk wire request data reply timeout_ms"
    }
    lassign $argv workspace boot command mailbox sk wire request data reply timeout
    set workspace [file normalize $workspace]
    foreach name {boot mailbox sk wire timeout} {set $name [expr {[set $name]}]}
    if {$boot ni {0 1} || $command ni {load begin finish rekey clear} ||
        $timeout < 1000 || $timeout > 120000 ||
        $mailbox < 0x100000 || $mailbox + 256 > 0x40000000 || $mailbox % 64 ||
        $sk < 0x100000 || $sk + 1632 > 0x40000000 || $sk % 64 ||
        $wire < 0x100000 || $wire + 972 > 0x40000000 || $wire % 64 ||
        [file size $request] != 256 || [file exists $reply] ||
        ($command eq "load" && [file size $data] != 1632) ||
        (($command eq "begin" || $command eq "finish" || $command eq "rekey") && [file size $data] != 972)} {
        error "Invalid M10 owned DDR request/arguments"
    }
    set ranges [list [list $mailbox 256] [list $sk 1632] [list $wire 972]]
    for {set i 0} {$i < [llength $ranges]} {incr i} {
        lassign [lindex $ranges $i] start_i size_i
        for {set j [expr {$i + 1}]} {$j < [llength $ranges]} {incr j} {
            lassign [lindex $ranges $j] start_j size_j
            if {$start_i < $start_j + $size_j && $start_j < $start_i + $size_i} {
                error "Overlapping M10 owned DDR buffers"
            }
        }
    }
    connect -url tcp:127.0.0.1:3121
    if {$boot} {
        targets -set -filter {name == "APU"}
        rst -system -stop
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        source "$workspace/m10/_ide/psinit/ps7_init.tcl"
        ps7_init
        targets -set -filter {name == "xc7z020"}
        fpga -file "$workspace/m10/_ide/bitstream/m01.bit"
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        ps7_post_config
        rst -processor
        dow -clear "$workspace/m10/build/m10.elf"
        con
        puts "M10_BOOT_OK"
    }
    targets -set -filter {name == "APU"}
    set start [clock milliseconds]
    while {[lindex [mrd -address-space AP0 -value $mailbox] 0] != 0x30314d45} {
        if {[clock milliseconds] - $start > 10000} {error "M10 boot timeout"}
        after 100
    }
    set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
    if {$state == 1 || $state == 4} {error "M10 job already active"}
    if {$command eq "load"} {mwr -address-space AP0 -bin -file $data $sk 408}
    if {$command eq "begin" || $command eq "finish" || $command eq "rekey"} {
        mwr -address-space AP0 -bin -file $data $wire 243
    }
    mwr -address-space AP0 -bin -file $request $mailbox 64
    mwr -address-space AP0 [expr {$mailbox+4}] 1
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
        if {$state == 2 || $state == 3} {break}
        if {[clock milliseconds] - $start > $timeout} {error "M10 job timeout"}
        after 20
    }
    mrd -address-space AP0 -bin -file $reply $mailbox 64
    disconnect
    puts "M10_JOB_DONE command=$command state=$state"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
