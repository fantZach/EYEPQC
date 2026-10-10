# Read-only PS DDR verification for a completed G6 secure cleanup.
# Usage: diag_addr diag_size frame_addr frame_size sealed_addr sealed_size tx_addr tx_size
# This script only connects, selects APU, reads AP0, and disconnects. It never
# stops/resets a target, loads an image, or writes memory/registers.

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

proc validate_range {name address size max_size} {
    if {$address < 0x00100000 || $address >= 0x40000000 ||
        $size <= 0 || $size > $max_size || ($address % 64) != 0 ||
        ($size % 4) != 0 || ($address + $size) > 0x40000000} {
        error "Invalid DDR range for $name"
    }
}

proc ranges_overlap {a_addr a_size b_addr b_size} {
    return [expr {$a_addr < ($b_addr + $b_size) &&
                  $b_addr < ($a_addr + $a_size)}]
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

proc read_zero_or {name address size} {
    set total_words [expr {$size / 4}]
    set aggregate 0
    set completed 0
    while {$completed < $total_words} {
        set count [expr {min(4096, $total_words - $completed)}]
        set chunk_address [expr {$address + 4 * $completed}]
        foreach word [mrd_u32 $chunk_address $count] {
            set aggregate [expr {$aggregate | $word}]
        }
        incr completed $count
    }
    set all_zero [expr {$aggregate == 0}]
    puts [format "G6_CLEANUP_RANGE name=%s bytes=%u words=%u zero=%u" \
        $name $size $total_words $all_zero]
    return $all_zero
}

set connected 0
if {[catch {
    if {[llength $argv] != 8} {
        error "usage: diag_addr diag_size frame_addr frame_size sealed_addr sealed_size tx_addr tx_size"
    }
    lassign $argv diag_addr diag_size frame_addr frame_size \
        sealed_addr sealed_size tx_addr tx_size
    foreach name {diag_addr diag_size frame_addr frame_size sealed_addr sealed_size tx_addr tx_size} {
        set $name [parse_u32 $name [set $name]]
    }

    if {$diag_size != 120} {
        error "Diagnostic size must match the 120-byte G6 cleanup ABI"
    }
    validate_range diag $diag_addr $diag_size 120
    foreach {name address size} [list \
        frame $frame_addr $frame_size \
        sealed $sealed_addr $sealed_size \
        tx $tx_addr $tx_size] {
        validate_range $name $address $size 1048576
    }
    foreach {a_addr a_size b_addr b_size} [list \
        $diag_addr $diag_size $frame_addr $frame_size \
        $diag_addr $diag_size $sealed_addr $sealed_size \
        $diag_addr $diag_size $tx_addr $tx_size \
        $frame_addr $frame_size $sealed_addr $sealed_size \
        $frame_addr $frame_size $tx_addr $tx_size \
        $sealed_addr $sealed_size $tx_addr $tx_size] {
        if {[ranges_overlap $a_addr $a_size $b_addr $b_size]} {
            error "Diagnostic and wipe-verification DDR ranges must not overlap"
        }
    }

    connect -url tcp:127.0.0.1:3121
    set connected 1
    targets -set -filter {name == "APU"}

    # G6_SECURE_CLEANUP_MAGIC, 30-word / 120-byte ABI. Keep the complete
    # diagnostic in memory; print status fields only, never buffer contents.
    set diag_before [mrd_u32 $diag_addr 30]
    set magic [lindex $diag_before 0]
    set stage_before [lindex $diag_before 1]
    set result_before [lindex $diag_before 2]
    set route_mode [lindex $diag_before 4]
    set dma_reset_status [lindex $diag_before 5]
    set capture_rx_status [lindex $diag_before 6]
    set crypto_rx_status [lindex $diag_before 7]
    set crypto_tx_status [lindex $diag_before 8]
    set gcm_status [lindex $diag_before 9]
    set diag_frame_addr [lindex $diag_before 10]
    set diag_frame_size [lindex $diag_before 11]
    set diag_frame_zero_or [lindex $diag_before 12]
    set diag_sealed_addr [lindex $diag_before 13]
    set diag_sealed_size [lindex $diag_before 14]
    set diag_sealed_zero_or [lindex $diag_before 15]
    set usb_quiesce_status [lindex $diag_before 16]
    set usb_flush_status [lindex $diag_before 17]
    set usb_prime_status [lindex $diag_before 18]
    set usb_completion_status [lindex $diag_before 19]
    set usb_poll_limit [lindex $diag_before 20]
    set usb_flush_polls [lindex $diag_before 21]
    set usb_prime_polls [lindex $diag_before 22]
    set usb_rebuild_status [lindex $diag_before 23]
    set diag_tx_addr [lindex $diag_before 24]
    set diag_tx_size [lindex $diag_before 25]
    set diag_tx_zero_or [lindex $diag_before 26]
    set usb_ownership_eprdystatus [lindex $diag_before 27]
    set usb_ownership_eprdy_polls [lindex $diag_before 28]
    set usb_cleanup_path [lindex $diag_before 29]

    if {$magic != 0x4736434c || $stage_before != 6 || $result_before != 0} {
        error "Cleanup diagnostic is not successful COMPLETE state"
    }
    if {$diag_frame_addr != $frame_addr || $diag_frame_size != $frame_size ||
        $diag_sealed_addr != $sealed_addr || $diag_sealed_size != $sealed_size ||
        $diag_tx_addr != $tx_addr || $diag_tx_size != $tx_size} {
        error "Cleanup diagnostic address/capacity does not match supplied ELF values"
    }
    if {$usb_ownership_eprdystatus != 0 || $usb_ownership_eprdy_polls == 0 ||
        $usb_cleanup_path < 1 || $usb_cleanup_path > 2} {
        error "Cleanup diagnostic does not prove USB ownership or a known cleanup path"
    }

    puts [format "G6_CLEANUP_DIAG magic=%08x stage=%u result=%u route=%u dma_reset=%08x capture_rx=%08x crypto_rx=%08x crypto_tx=%08x gcm=%08x usb_quiesce=%u usb_flush=%u usb_prime=%u usb_completion=%u usb_poll_limit=%u usb_flush_polls=%u usb_prime_polls=%u usb_rebuild=%u usb_ownership_eprdystatus=%08x usb_ownership_eprdy_polls=%u usb_cleanup_path=%u diag_zero_or_frame=%u diag_zero_or_sealed=%u diag_zero_or_tx=%u" \
        $magic $stage_before $result_before $route_mode $dma_reset_status \
        $capture_rx_status $crypto_rx_status $crypto_tx_status $gcm_status \
        $usb_quiesce_status $usb_flush_status $usb_prime_status \
        $usb_completion_status $usb_poll_limit $usb_flush_polls \
        $usb_prime_polls $usb_rebuild_status $usb_ownership_eprdystatus \
        $usb_ownership_eprdy_polls $usb_cleanup_path $diag_frame_zero_or \
        $diag_sealed_zero_or $diag_tx_zero_or]

    # Match g3_usb_cleanup_stop_dma_and_clear_gcm(): route 3, successful reset,
    # no DMA error/IRQ error bits, and each channel halted or idle. These masks
    # are the Zynq AXI DMA definitions used by the candidate008 BSP.
    set dma_error_mask 0x00004770 ;# ERR_ALL 0x00000770 | IRQ_ERROR 0x00004000
    set dma_stopped_mask 0x00000003 ;# HALTED 0x1 | IDLE 0x2
    foreach {name status} [list \
        capture_rx $capture_rx_status \
        crypto_rx $crypto_rx_status \
        crypto_tx $crypto_tx_status] {
        if {($status & $dma_error_mask) != 0 ||
            ($status & $dma_stopped_mask) == 0} {
            error "Cleanup diagnostic does not prove $name DMA stopped without errors"
        }
    }
    if {$route_mode != 3 || $dma_reset_status != 0 ||
        ($gcm_status & 7) != 0 ||
        $usb_quiesce_status != 0 || $usb_flush_status != 0 ||
        $usb_prime_status != 0 || $usb_completion_status != 0 ||
        $usb_rebuild_status != 0 ||
        $diag_frame_zero_or != 0 || $diag_sealed_zero_or != 0 ||
        $diag_tx_zero_or != 0} {
        error "Cleanup diagnostic does not prove successful route/DMA/GCM/USB cleanup"
    }

    set frame_zero [read_zero_or frame $frame_addr $frame_size]
    set sealed_zero [read_zero_or sealed $sealed_addr $sealed_size]
    set tx_zero [read_zero_or tx $tx_addr $tx_size]
    set total_bytes [expr {$frame_size + $sealed_size + $tx_size}]

    set diag_after [mrd_u32 $diag_addr 30]
    set stage_after [lindex $diag_after 1]
    set result_after [lindex $diag_after 2]
    if {$stage_after != $stage_before || $stage_after != 6 ||
        $result_after != 0 || $diag_after ne $diag_before} {
        error "Cleanup diagnostic changed or left successful COMPLETE state during readback"
    }
    puts [format "G6_CLEANUP_READBACK frame_zero=%u sealed_zero=%u tx_zero=%u total_bytes=%u stage_before=%u stage_after=%u scope=PS_AP0_DDR_only pl_gcm_full_readback=not_proven" \
        $frame_zero $sealed_zero $tx_zero $total_bytes $stage_before $stage_after]
    disconnect
    set connected 0
    if {!$frame_zero || !$sealed_zero || !$tx_zero} {
        error "One or more PS DDR cleanup ranges contain nonzero data"
    }
    puts "G6_CLEANUP_READBACK_PASS"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    if {$connected} {
        catch {disconnect}
        set connected 0
    }
    exit 1
}
