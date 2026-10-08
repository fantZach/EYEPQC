# Read-only post-session health snapshot for an already-loaded candidate G6 image.
if {[catch {
    if {[llength $argv] != 6} {
        error "usage: status_addr fatal_addr control_addr transport_addr ready_addr transport_diag_addr"
    }
    lassign $argv status_addr fatal_addr control_addr transport_addr ready_addr transport_diag_addr
    foreach name {status_addr fatal_addr control_addr transport_addr ready_addr transport_diag_addr} {
        set $name [expr {[set $name]}]
        set address [set $name]
        if {$address < 0x100000 || $address >= 0x40000000 || ($address % 4)} {
            error "Invalid ELF-owned DDR address: $name"
        }
    }
    if {$transport_diag_addr % 64} { error "Invalid transport diagnostic alignment" }
    connect -url tcp:127.0.0.1:3121
    targets -set -filter {name == "APU"}
    set status [lindex [mrd -address-space AP0 -value $status_addr] 0]
    set fatal [lindex [mrd -address-space AP0 -value $fatal_addr] 0]
    set control [lindex [mrd -address-space AP0 -value $control_addr] 0]
    set transport [lindex [mrd -address-space AP0 -value $transport_addr] 0]
    set ready [lindex [mrd -address-space AP0 -value $ready_addr] 0]
    set words {}
    for {set offset 0} {$offset < 32} {incr offset 4} {
        lappend words [lindex [mrd -address-space AP0 -value [expr {$transport_diag_addr+$offset}]] 0]
    }
    lassign $words send_status resume_status failure_phase usb_ready failure_epoch \
        last_successful_frame_id transport_error_count transport_reserved
    puts [format "G6_AUTO_HEALTH status=%u fatal=%u control=%u transport=%u ready=%08x" \
        $status $fatal $control $transport $ready]
    puts [format "G6_AUTO_TRANSPORT_FAILURE send_status=%u resume_status=%u phase=%u usb_ready=%u connection_epoch=%u last_successful_frame_id=%u transport_error_count=%u" \
        $send_status $resume_status $failure_phase $usb_ready $failure_epoch \
        $last_successful_frame_id $transport_error_count]
    disconnect
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
