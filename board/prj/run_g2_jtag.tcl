# Volatile JTAG only: load G2 bit/ELF and exchange ELF-owned DDR buffers.
if {[catch {
    if {[llength $argv] != 10} {
        error "usage: workspace boot mailbox tx rx request payload reply output timeout_ms"
    }
    lassign $argv workspace boot mailbox tx rx request payload reply output timeout
    set workspace [file normalize $workspace]
    foreach name {boot mailbox tx rx timeout} {set $name [expr {[set $name]}]}
    if {$boot ni {0 1} || $timeout < 1000 || $timeout > 60000 ||
        $mailbox < 0x100000 || $mailbox + 192 > 0x40000000 || $mailbox % 64 ||
        $tx < 0x100000 || $tx + 1472 > 0x40000000 || $tx % 64 ||
        $rx < 0x100000 || $rx + 1536 > 0x40000000 || $rx % 64 ||
        [file size $request] != 192 || [file size $payload] < 4 ||
        [file size $payload] > 1400 || [file size $payload] % 4 ||
        [file exists $reply] || [file exists $output]} {
        error "Invalid owned DDR request/arguments"
    }
    set handle [open $request rb]
    fconfigure $handle -translation binary
    set blob [read $handle 16]
    close $handle
    binary scan $blob i4 words
    set length [lindex $words 2]
    if {$length < 0 || $length > 1400 ||
        [file size $payload] != ($length == 0 ? 4 : (($length+3)/4)*4)} {
        error "Invalid request length/payload"
    }
    connect -url tcp:127.0.0.1:3121
    if {$boot} {
        targets -set -filter {name == "APU"}
        rst -system -stop
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        source "$workspace/g2_crypto/_ide/psinit/ps7_init.tcl"
        ps7_init
        targets -set -filter {name == "xc7z020"}
        fpga -file "$workspace/g2_crypto/_ide/bitstream/m01.bit"
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        ps7_post_config
        rst -processor
        dow -clear "$workspace/g2_crypto/build/g2_crypto.elf"
        con
        puts "G2_BOOT_OK"
    }
    targets -set -filter {name == "APU"}
    set start [clock milliseconds]
    while {[lindex [mrd -address-space AP0 -value $mailbox] 0] != 0x32474345} {
        if {[clock milliseconds] - $start > 10000} {error "G2 boot/mailbox timeout"}
        after 100
    }
    set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
    if {$state == 1 || $state == 4} {error "G2 job already active"}
    mwr -address-space AP0 -bin -file $request $mailbox 48
    mwr -address-space AP0 -bin -file $payload $tx [expr {[file size $payload]/4}]
    mwr -address-space AP0 [expr {$mailbox+4}] 1
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
        if {$state == 2 || $state == 3} {break}
        if {[clock milliseconds] - $start > $timeout} {error "G2 command timeout"}
        after 20
    }
    mrd -address-space AP0 -bin -file $reply $mailbox 48
    if {$state == 2} {
        mrd -address-space AP0 -bin -file $output $rx [expr {($length+16+3)/4}]
    }
    if {$state != 2} {
        set status [lindex [mrd -address-space AP0 -value [expr {$mailbox+16}]] 0]
        disconnect
        error "G2 board job failed status=$status; inspect mailbox"
    }
    disconnect
    puts "G2_JOB_DONE length=$length"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
