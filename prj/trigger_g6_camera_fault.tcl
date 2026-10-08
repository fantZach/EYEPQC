# Trigger one controlled camera-reset/DMA-stall experiment through owned DDR only.
# Does not reset the PS, reload PL, write storage, or provision secrets.
if {[catch {
    if {[llength $argv] != 5} {
        error "usage: inject_addr diag_addr ready_addr status_addr timeout_ms"
    }
    lassign $argv inject_addr diag_addr ready_addr status_addr timeout
    foreach name {inject_addr diag_addr ready_addr status_addr timeout} {
        set $name [expr {[set $name]}]
    }
    foreach name {inject_addr diag_addr ready_addr status_addr} {
        set address [set $name]
        if {$address < 0x100000 || $address >= 0x40000000 || ($address % 4)} {
            error "Invalid ELF-owned DDR address: $name"
        }
    }
    if {$inject_addr % 64 || $diag_addr % 64 || $timeout < 1000 || $timeout > 30000} {
        error "Invalid alignment or timeout"
    }
    connect -url tcp:127.0.0.1:3121
    targets -set -filter {name == "APU"}
    set ready [lindex [mrd -address-space AP0 -value $ready_addr] 0]
    set status [lindex [mrd -address-space AP0 -value $status_addr] 0]
    set inject [lindex [mrd -address-space AP0 -value $inject_addr] 0]
    set state [lindex [mrd -address-space AP0 -value [expr {$diag_addr+4}]] 0]
    if {$ready != 0x36475345 || $status != 1 || $inject != 0 || $state != 0} {
        error "G6 variant not ready or diagnostic is not idle"
    }

    mwr -address-space AP0 $inject_addr 1
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$diag_addr+4}]] 0]
        if {$state == 2 || $state == 3} {break}
        if {[clock milliseconds] - $start > $timeout} {error "Camera/DMA diagnostic timeout"}
        after 50
    }

    set words {}
    for {set offset 0} {$offset < 56} {incr offset 4} {
        lappend words [lindex [mrd -address-space AP0 -value [expr {$diag_addr+$offset}]] 0]
    }
    lassign $words magic state stage result camera_stopped sr_armed busy_armed \
        sr_timeout busy_timeout elapsed reset_status camera_recovered frame_length frame_hash
    puts [format "G6_CAMERA_FAULT_DIAG magic=%08x state=%u stage=%u result=%u camera_stopped=%08x sr_armed=%08x busy_armed=%u sr_timeout=%08x busy_timeout=%u elapsed_us=%u reset_sr=%08x camera_recovered=%08x frame_length=%u frame_hash=%08x" \
        $magic $state $stage $result $camera_stopped $sr_armed $busy_armed $sr_timeout \
        $busy_timeout $elapsed $reset_status $camera_recovered $frame_length $frame_hash]

    if {$magic != 0x47434431 || $state != 2 || $stage != 7 || $result != 0 ||
        $busy_armed != 1 || $busy_timeout != 1 || $elapsed < 5000 ||
        ($camera_stopped & 0x00990000) != 0x00100000 ||
        ($camera_recovered & 0x0080ffff) != 0x00805640 ||
        $frame_length < 4 || $frame_length > 65536} {
        error "Diagnostic did not prove real DMA timeout and camera frame recovery"
    }
    disconnect
    puts "G6_CAMERA_FAULT_DIAG_OK"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
