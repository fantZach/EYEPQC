# Read-only PS DDR verification for a completed G6 secure cleanup.
# Usage: diag_addr diag_size frame_addr frame_size sealed_addr sealed_size tx_addr tx_size
#        session_addr session_size hello_addr hello_size ack_addr ack_size
# Development cleanup profile appends address/size pairs for private_key,
# random_seed, g6_sk_load, g6_seed_load, random_counter, and g6_ready.
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

proc validate_range {name address size max_size {alignment 64}} {
    if {$address < 0x00100000 || $address >= 0x40000000 ||
        $size <= 0 || $size > $max_size || ($address % $alignment) != 0 ||
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
    set argument_count [llength $argv]
    if {$argument_count != 14 && $argument_count != 26} {
        error "usage: 14 base cleanup args; append 12 development key args when using the dev cleanup profile"
    }
    set dev_cleanup [expr {$argument_count == 26}]
    lassign $argv diag_addr diag_size frame_addr frame_size \
        sealed_addr sealed_size tx_addr tx_size session_addr session_size \
        hello_addr hello_size ack_addr ack_size
    if {$dev_cleanup} {
        lassign [lrange $argv 14 end] private_key_addr private_key_size \
            random_seed_addr random_seed_size g6_sk_load_addr g6_sk_load_size \
            g6_seed_load_addr g6_seed_load_size random_counter_addr random_counter_size \
            g6_ready_addr g6_ready_size
    }
    set numeric_names {diag_addr diag_size frame_addr frame_size sealed_addr sealed_size \
        tx_addr tx_size session_addr session_size hello_addr hello_size ack_addr ack_size}
    if {$dev_cleanup} {
        lappend numeric_names private_key_addr private_key_size random_seed_addr random_seed_size \
            g6_sk_load_addr g6_sk_load_size g6_seed_load_addr g6_seed_load_size \
            random_counter_addr random_counter_size g6_ready_addr g6_ready_size
    }
    foreach name $numeric_names {
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
    if {$session_size != 192 || $hello_size != 48 || $ack_size != 48} {
        error "CPU secret/cache sizes do not match the G6 production ABI"
    }
    foreach {name address size} [list \
        session $session_addr $session_size \
        hello $hello_addr $hello_size \
        ack $ack_addr $ack_size] {
        validate_range $name $address $size 256 4
    }
    set owned_ranges [list \
        [list diag $diag_addr $diag_size] [list frame $frame_addr $frame_size] \
        [list sealed $sealed_addr $sealed_size] [list tx $tx_addr $tx_size] \
        [list session $session_addr $session_size] [list hello $hello_addr $hello_size] \
        [list ack $ack_addr $ack_size]]
    if {$dev_cleanup} {
        foreach {name address size max_size alignment} [list \
            private_key $private_key_addr $private_key_size 1632 4 \
            random_seed $random_seed_addr $random_seed_size 32 4 \
            g6_sk_load $g6_sk_load_addr $g6_sk_load_size 1632 64 \
            g6_seed_load $g6_seed_load_addr $g6_seed_load_size 32 64 \
            random_counter $random_counter_addr $random_counter_size 8 4 \
            g6_ready $g6_ready_addr $g6_ready_size 4 4] {
            if {$size != $max_size} { error "Invalid development key range size for $name" }
            validate_range $name $address $size $max_size $alignment
            lappend owned_ranges [list $name $address $size]
        }
    }
    for {set i 0} {$i < [llength $owned_ranges]} {incr i} {
        lassign [lindex $owned_ranges $i] name_i address_i size_i
        for {set j [expr {$i + 1}]} {$j < [llength $owned_ranges]} {incr j} {
            lassign [lindex $owned_ranges $j] name_j address_j size_j
            if {[ranges_overlap $address_i $size_i $address_j $size_j]} {
                error "Cleanup DDR ranges overlap: $name_i / $name_j"
            }
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
    set session_keys_zero [read_zero_or session_keys [expr {$session_addr + 64}] 80]
    set session_counters_zero [read_zero_or session_counters [expr {$session_addr + 144}] 40]
    set hello_zero [read_zero_or hello $hello_addr $hello_size]
    set ack_zero [read_zero_or ack $ack_addr $ack_size]
    set total_bytes [expr {$frame_size + $sealed_size + $tx_size + 120 +
                           $hello_size + $ack_size}]
    if {$dev_cleanup} {
        set private_key_zero [read_zero_or private_key $private_key_addr $private_key_size]
        set random_seed_zero [read_zero_or random_seed $random_seed_addr $random_seed_size]
        set g6_sk_load_zero [read_zero_or g6_sk_load $g6_sk_load_addr $g6_sk_load_size]
        set g6_seed_load_zero [read_zero_or g6_seed_load $g6_seed_load_addr $g6_seed_load_size]
        set random_counter_zero [read_zero_or random_counter $random_counter_addr $random_counter_size]
        set g6_ready_zero [read_zero_or g6_ready $g6_ready_addr $g6_ready_size]
        incr total_bytes [expr {$private_key_size + $random_seed_size + \
                                $g6_sk_load_size + $g6_seed_load_size + \
                                $random_counter_size + $g6_ready_size}]
    }

    set diag_after [mrd_u32 $diag_addr 30]
    set stage_after [lindex $diag_after 1]
    set result_after [lindex $diag_after 2]
    if {$stage_after != $stage_before || $stage_after != 6 ||
        $result_after != 0 || $diag_after ne $diag_before} {
        error "Cleanup diagnostic changed or left successful COMPLETE state during readback"
    }
    set summary [format "G6_CLEANUP_READBACK frame_zero=%u sealed_zero=%u tx_zero=%u session_keys_zero=%u session_counters_zero=%u hello_zero=%u ack_zero=%u total_bytes=%u stage_before=%u stage_after=%u scope=PS_AP0_DDR_only pl_gcm_full_readback=not_proven" \
        $frame_zero $sealed_zero $tx_zero $session_keys_zero $session_counters_zero \
        $hello_zero $ack_zero $total_bytes $stage_before $stage_after]
    if {$dev_cleanup} {
        append summary [format " private_key_zero=%u random_seed_zero=%u g6_sk_load_zero=%u g6_seed_load_zero=%u random_counter_zero=%u g6_ready_zero=%u" \
            $private_key_zero $random_seed_zero $g6_sk_load_zero $g6_seed_load_zero \
            $random_counter_zero $g6_ready_zero]
    }
    puts $summary
    disconnect
    set connected 0
    if {!$frame_zero || !$sealed_zero || !$tx_zero || !$session_keys_zero ||
        !$session_counters_zero || !$hello_zero || !$ack_zero} {
        error "One or more PS DDR cleanup ranges contain nonzero data"
    }
    if {$dev_cleanup && (!$private_key_zero || !$random_seed_zero ||
        !$g6_sk_load_zero || !$g6_seed_load_zero || !$random_counter_zero || !$g6_ready_zero)} {
        error "One or more development key ranges contain nonzero data"
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
