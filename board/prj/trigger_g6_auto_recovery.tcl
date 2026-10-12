# Exercise one candidate G6 camera/DMA recovery. Trigger only removes the source
# or stalls capture routing; firmware must execute the normal 3-second S2MM wait.
if {[catch {
    if {[llength $argv] != 12} {
        error "usage: request_addr diag_addr ready_addr status_addr mode timeout_ms capture_errors dropped fatal control transport transport_diag"
    }
    lassign $argv request_addr diag_addr ready_addr status_addr mode timeout \
        capture_errors_addr dropped_addr fatal_addr control_addr transport_addr transport_diag_addr
    foreach name {request_addr diag_addr ready_addr status_addr mode timeout capture_errors_addr dropped_addr fatal_addr control_addr transport_addr transport_diag_addr} {
        set $name [expr {[set $name]}]
    }
    foreach name {request_addr diag_addr ready_addr status_addr capture_errors_addr dropped_addr fatal_addr control_addr transport_addr transport_diag_addr} {
        set address [set $name]
        if {$address < 0x100000 || $address >= 0x40000000 || ($address % 4)} {
            error "Invalid ELF-owned DDR address: $name"
        }
    }
    if {$request_addr % 64 || $diag_addr % 64 || $mode < 1 || $mode > 2 ||
        $timeout < 5000 || $timeout > 60000} {
        error "Invalid trigger mode, alignment, or timeout"
    }

    connect -url tcp:127.0.0.1:3121
    targets -set -filter {name == "APU"}
    set ready [lindex [mrd -address-space AP0 -value $ready_addr] 0]
    set status [lindex [mrd -address-space AP0 -value $status_addr] 0]
    set request [lindex [mrd -address-space AP0 -value $request_addr] 0]
    set state [lindex [mrd -address-space AP0 -value [expr {$diag_addr+4}]] 0]
    set magic [lindex [mrd -address-space AP0 -value $diag_addr] 0]
    set capture_before [lindex [mrd -address-space AP0 -value $capture_errors_addr] 0]
    set dropped_before [lindex [mrd -address-space AP0 -value $dropped_addr] 0]
    set fatal_before [lindex [mrd -address-space AP0 -value $fatal_addr] 0]
    set control_before [lindex [mrd -address-space AP0 -value $control_addr] 0]
    set transport_before [lindex [mrd -address-space AP0 -value $transport_addr] 0]
    puts [format "G6_AUTO_PREFLIGHT ready=%u status=%u request=%u state=%u magic=%08x capture=%u dropped=%u fatal=%u control=%u transport=%u" \
        $ready $status $request $state $magic $capture_before $dropped_before $fatal_before $control_before $transport_before]
    if {$ready != 0x36475345 || $status != 1 || $request != 0 ||
        $magic != 0x47415231 || ($state != 0 && $state != 2)} {
        error "Candidate G6 not ready or previous recovery state was not reset"
    }
    mwr -address-space AP0 [expr {$diag_addr+4}] 0

    mwr -address-space AP0 $request_addr $mode
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$diag_addr+4}]] 0]
        if {$state == 2 || $state == 3} {break}
        if {[clock milliseconds] - $start > $timeout} {error "Candidate recovery timeout"}
        after 50
    }

    set words {}
    for {set offset 0} {$offset < 56} {incr offset 4} {
        lappend words [lindex [mrd -address-space AP0 -value [expr {$diag_addr+$offset}]] 0]
    }
    lassign $words magic state stage trigger_mode observation status_register \
        busy_start busy_end elapsed recovery_status camera_status frame_length \
        recovery_count malformed_drops
    set capture_after [lindex [mrd -address-space AP0 -value $capture_errors_addr] 0]
    set dropped_after [lindex [mrd -address-space AP0 -value $dropped_addr] 0]
    set fatal_after [lindex [mrd -address-space AP0 -value $fatal_addr] 0]
    set control_after [lindex [mrd -address-space AP0 -value $control_addr] 0]
    set transport_after [lindex [mrd -address-space AP0 -value $transport_addr] 0]
    set status_after [lindex [mrd -address-space AP0 -value $status_addr] 0]
    set transport_words {}
    for {set offset 0} {$offset < 32} {incr offset 4} {
        lappend transport_words [lindex [mrd -address-space AP0 -value [expr {$transport_diag_addr+$offset}]] 0]
    }
    lassign $transport_words send_status resume_status failure_phase usb_ready \
        failure_epoch last_successful_frame_id transport_error_count transport_reserved

    puts [format "G6_AUTO_RECOVERY_DIAG magic=%08x state=%u stage=%u mode=%u observation=%u sr=%08x busy_start=%u busy_deadline=%u elapsed_us=%u recovery_status=%u camera_status=%08x frame_length=%u recovery_count=%u malformed_drops=%u" \
        $magic $state $stage $trigger_mode $observation $status_register $busy_start \
        $busy_end $elapsed $recovery_status $camera_status $frame_length $recovery_count $malformed_drops]
    puts [format "G6_AUTO_COUNTERS capture=%u->%u dropped=%u->%u fatal=%u->%u control=%u->%u transport=%u->%u status=%u->%u" \
        $capture_before $capture_after $dropped_before $dropped_after $fatal_before $fatal_after \
        $control_before $control_after $transport_before $transport_after $status $status_after]
    puts [format "G6_AUTO_TRANSPORT_FAILURE send_status=%u resume_status=%u phase=%u usb_ready=%u connection_epoch=%u last_successful_frame_id=%u transport_error_count=%u" \
        $send_status $resume_status $failure_phase $usb_ready $failure_epoch \
        $last_successful_frame_id $transport_error_count]

    if {$magic != 0x47415231 || $state != 2 || $stage != 5 || $trigger_mode != $mode ||
        $observation != 3 || $busy_start != 1 || $busy_end != 1 ||
        $elapsed < 3000000 || ($status_register & 0x00004000) != 0 ||
        $recovery_status != 0 || ($camera_status & 0x0080ffff) != 0x00805640 ||
        $capture_after != $capture_before + 1 || $dropped_after != $dropped_before + 1 ||
        $fatal_after != $fatal_before || $control_after != $control_before ||
        $transport_after != $transport_before || $status_after != 1} {
        error "Real Busy deadline, bounded recovery, or counter deltas not proven"
    }
    disconnect
    puts "G6_AUTO_RECOVERY_OK"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
