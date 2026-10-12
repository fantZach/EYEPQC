# Development-only: load test private key and fresh host RNG seed into volatile DDR.
if {[catch {
    if {[llength $argv] != 6} {error "usage: provision_g6_jtag.tcl sk_file seed_file sk_addr seed_addr ready_addr status_addr"}
    lassign $argv sk seed sk_addr seed_addr ready_addr status_addr
    foreach name {sk_addr seed_addr ready_addr status_addr} {
        set $name [expr {[set $name]}]
        if {[set $name] < 0x100000 || [set $name] >= 0x40000000 || [set $name] % 64} {
            error "Invalid ELF-owned DDR address: $name"
        }
    }
    set ranges [list [list $sk_addr 1632] [list $seed_addr 32] \
                     [list $ready_addr 4] [list $status_addr 4]]
    for {set i 0} {$i < [llength $ranges]} {incr i} {
        lassign [lindex $ranges $i] start_i size_i
        for {set j [expr {$i + 1}]} {$j < [llength $ranges]} {incr j} {
            lassign [lindex $ranges $j] start_j size_j
            if {$start_i < $start_j + $size_j && $start_j < $start_i + $size_i} {
                error "Overlapping G6 provisioning buffers"
            }
        }
    }
    if {[file size $sk] != 1632 || [file size $seed] != 32 ||
        $sk_addr + 1632 > 0x40000000 || $seed_addr + 32 > 0x40000000} {
        error "Invalid G6 provision input"
    }
    connect -url tcp:127.0.0.1:3121
    targets -set -filter {name == "APU"}
    mwr -address-space AP0 -bin -file $sk $sk_addr 408
    mwr -address-space AP0 -bin -file $seed $seed_addr 8
    mwr -address-space AP0 $ready_addr 0x36475345
    set start [clock milliseconds]
    while {1} {
        set value [lindex [mrd -address-space AP0 -value $status_addr] 0]
        if {$value == 1} break
        if {$value == 0xffffffff} {error "Board rejected G6 private key or seed"}
        if {[clock milliseconds] - $start > 10000} {error "G6 provision timeout"}
        after 50
    }
    puts "G6_PROVISIONED"
    disconnect
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
