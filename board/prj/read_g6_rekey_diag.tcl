# Read-only AP0 snapshot of the candidate G6 REKEY/HELLO diagnostic.
# Usage: diag_addr diag_size
# This script connects to APU and reads DDR only. It never stops/resets a
# target, loads an image, writes memory/registers, or reads packet/key payloads.

proc parse_u32 {name value} {
    if {![regexp {^(0[xX][0-9a-fA-F]+|[0-9]+)$} $value]} {
        error "Invalid unsigned integer for $name"
    }
    set parsed [expr {$value}]
    if {$parsed < 0 || $parsed > 0xffffffff} {
        error "Out-of-range unsigned integer for $name"
    }
    return $parsed
}

proc validate_range {address size} {
    if {$address < 0x00100000 || $address >= 0x40000000 ||
        $size != 144 || ($address % 64) != 0 ||
        ($address + $size) > 0x40000000} {
        error "Invalid DDR range or G6 rekey diagnostic size"
    }
}

proc mrd_u32 {address count} {
    set values [mrd -address-space AP0 -value $address $count]
    if {[llength $values] != $count} {
        error "AP0 read returned an unexpected word count"
    }
    set parsed {}
    foreach value $values {
        if {![regexp {^(0[xX][0-9a-fA-F]+|[0-9]+)$} $value]} {
            error "AP0 read returned a non-numeric word"
        }
        set word [expr {$value}]
        if {$word < 0 || $word > 0xffffffff} {
            error "AP0 read returned a word outside uint32 range"
        }
        lappend parsed $word
    }
    return $parsed
}

set connected 0
if {[catch {
    if {[llength $argv] != 2} {
        error "usage: diag_addr diag_size"
    }
    lassign $argv diag_addr diag_size
    set diag_addr [parse_u32 diag_addr $diag_addr]
    set diag_size [parse_u32 diag_size $diag_size]
    validate_range $diag_addr $diag_size

    connect -url tcp:127.0.0.1:3121
    set connected 1
    targets -set -filter {name == "APU"}

    # G6_REKEY_DIAG_MAGIC, version 2, 36-word / 144-byte ABI.
    # The double sequence check rejects a torn snapshot while firmware updates.
    set before [mrd_u32 $diag_addr 36]
    set magic [lindex $before 0]
    set version [lindex $before 1]
    set size_bytes [lindex $before 2]
    set sequence [lindex $before 3]
    set tx_completion_count [lindex $before 28]
    set tx_completion_status [lindex $before 29]
    set tx_completion_token [lindex $before 30]
    set tx_completion_residual [lindex $before 31]
    set tx_completion_requested [lindex $before 32]
    set tx_completion_expected [lindex $before 33]
    set tx_completion_match_flags [lindex $before 34]
    set sequence_end [lindex $before 35]
    set after [mrd_u32 $diag_addr 36]
    set after_sequence [lindex $after 3]
    set after_sequence_end [lindex $after 35]

    if {$magic != 0x47365244 || $version != 2 || $size_bytes != 144} {
        error "G6 rekey diagnostic magic/version/size mismatch"
    }
    if {$sequence != $sequence_end || ($sequence & 1) != 0 ||
        $after_sequence != $sequence || $after_sequence_end != $sequence_end ||
        $after ne $before} {
        error "G6 rekey diagnostic changed during read or is not stable"
    }

    set phase [lindex $before 4]
    if {$phase > 5} { error "G6 rekey diagnostic phase is outside ABI enum" }
    set phase_name [lindex {WAIT_HELLO WAIT_KEM WAIT_FINISHED WAIT_START STREAM FAULT} $phase]
    set last_control_type [lindex $before 5]
    set received_control_count [lindex $before 6]
    set hello_attempt_count [lindex $before 7]
    set hello_ack_send_attempts [lindex $before 8]
    set hello_ack_send_status [lindex $before 9]
    set cleanup_count [lindex $before 10]
    set cleanup_last_result [lindex $before 11]
    set usb_configured [lindex $before 12]
    set usb_dtr [lindex $before 13]
    set connection_epoch [lindex $before 14]
    set tx_ready [lindex $before 15]
    set rx_bytes_buffered [lindex $before 16]
    set rx_head [lindex $before 17]
    set rx_tail [lindex $before 18]
    set rx_bad [lindex $before 19]
    set ep1_prime [lindex $before 20]
    set ep1_ready [lindex $before 21]
    set epcr1 [lindex $before 22]
    set ep1_completion [lindex $before 23]
    set ep1_flush [lindex $before 24]
    set control_errors [lindex $before 25]
    set fatal_errors [lindex $before 26]
    set transport_errors [lindex $before 27]

    foreach value [list $usb_configured $usb_dtr $tx_ready $rx_bad] {
        if {$value > 1} { error "G6 rekey diagnostic boolean field is invalid" }
    }
    if {$rx_bytes_buffered > 2047 || $rx_head > 2047 || $rx_tail > 2047} {
        error "G6 rekey diagnostic RX ring field is outside bounds"
    }
    if {$tx_completion_status ni {0 3 4 5 4294967295} ||
        $tx_completion_match_flags > 31 ||
        ($tx_completion_residual != 4294967295 && $tx_completion_residual > 16384) ||
        ($tx_completion_requested != 4294967295 && $tx_completion_requested > 16384) ||
        ($tx_completion_expected != 4294967295 && $tx_completion_expected > 16384)} {
        error "G6 rekey diagnostic TX completion field is outside bounds"
    }

    puts [format "G6_REKEY_DIAG abi=%u sequence=%u phase=%s phase_id=%u last_control_type=%u received_controls=%u hello_attempts=%u hello_ack_send_attempts=%u hello_ack_send_status=%08x cleanup_count=%u cleanup_last_result=%08x usb_configured=%u usb_dtr=%u connection_epoch=%u tx_ready=%u rx_bytes_buffered=%u rx_head=%u rx_tail=%u rx_bad=%u ep1_prime=%08x ep1_ready=%08x epcr1=%08x ep1_completion=%08x ep1_flush=%08x control_errors=%u fatal_errors=%u transport_errors=%u tx_completion_count=%u tx_completion_status=%08x tx_completion_token=%08x tx_completion_residual=%u tx_completion_requested=%u tx_completion_expected=%u tx_completion_match_flags=%08x scope=PS_AP0_DDR_diagnostic_only payload_or_keys=not_read" \
        $version $sequence $phase_name $phase $last_control_type \
        $received_control_count $hello_attempt_count $hello_ack_send_attempts \
        $hello_ack_send_status $cleanup_count $cleanup_last_result \
        $usb_configured $usb_dtr $connection_epoch $tx_ready \
        $rx_bytes_buffered $rx_head $rx_tail $rx_bad $ep1_prime $ep1_ready \
        $epcr1 $ep1_completion $ep1_flush $control_errors $fatal_errors \
        $transport_errors $tx_completion_count $tx_completion_status \
        $tx_completion_token $tx_completion_residual $tx_completion_requested \
        $tx_completion_expected $tx_completion_match_flags]

    disconnect
    set connected 0
    puts "G6_REKEY_DIAG_READ_OK"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    if {$connected} {
        catch {disconnect}
        set connected 0
    }
    exit 1
}
