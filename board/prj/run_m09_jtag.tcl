# M09 volatile JTAG mailbox. All addresses come from the validated ELF manifest.
if {[catch {
    if {[llength $argv] != 10} {
        error "usage: workspace boot command mailbox sk ct request data reply timeout_ms"
    }
    lassign $argv workspace boot command mailbox sk ct request data reply timeout
    set workspace [file normalize $workspace]
    foreach name {boot mailbox sk ct timeout} {set $name [expr {[set $name]}]}
    if {$boot ni {0 1} || $command ni {load decap clear} ||
        $timeout < 1000 || $timeout > 120000 ||
        $mailbox < 0x100000 || $mailbox + 128 > 0x40000000 || $mailbox % 64 ||
        $sk < 0x100000 || $sk + 1632 > 0x40000000 || $sk % 64 ||
        $ct < 0x100000 || $ct + 768 > 0x40000000 || $ct % 64 ||
        [file size $request] != 128 || [file exists $reply] ||
        ($command eq "load" && [file size $data] != 1632) ||
        ($command eq "decap" && [file size $data] != 768)} {
        error "Invalid M09 owned DDR request/arguments"
    }
    set ranges [list [list $mailbox 128] [list $sk 1632] [list $ct 768]]
    for {set i 0} {$i < [llength $ranges]} {incr i} {
        lassign [lindex $ranges $i] start_i size_i
        for {set j [expr {$i + 1}]} {$j < [llength $ranges]} {incr j} {
            lassign [lindex $ranges $j] start_j size_j
            if {$start_i < $start_j + $size_j && $start_j < $start_i + $size_i} {
                error "Overlapping M09 owned DDR buffers"
            }
        }
    }
    connect -url tcp:127.0.0.1:3121
    if {$boot} {
        targets -set -filter {name == "APU"}
        rst -system -stop
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        source "$workspace/m09/_ide/psinit/ps7_init.tcl"
        ps7_init
        ps7_post_config
        rst -processor
        dow -clear "$workspace/m09/build/m09.elf"
        con
        puts "M09_BOOT_OK"
    }
    targets -set -filter {name == "APU"}
    set start [clock milliseconds]
    while {[lindex [mrd -address-space AP0 -value $mailbox] 0] != 0x39304d45} {
        if {[clock milliseconds] - $start > 10000} {error "M09 boot timeout"}
        after 100
    }
    set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
    if {$state == 1 || $state == 4} {error "M09 job already active"}
    if {$command eq "load"} {mwr -address-space AP0 -bin -file $data $sk 408}
    if {$command eq "decap"} {mwr -address-space AP0 -bin -file $data $ct 192}
    mwr -address-space AP0 -bin -file $request $mailbox 32
    mwr -address-space AP0 [expr {$mailbox+4}] 1
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
        if {$state == 2 || $state == 3} {break}
        if {[clock milliseconds] - $start > $timeout} {error "M09 job timeout"}
        after 20
    }
    mrd -address-space AP0 -bin -file $reply $mailbox 32
    disconnect
    if {$state != 2} {error "M09 board job failed; inspect reply"}
    puts "M09_JOB_DONE command=$command"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
