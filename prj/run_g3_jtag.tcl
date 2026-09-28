# Volatile JTAG only; read ELF-owned real JPEG and encrypted DDR packet stream.
if {[catch {
    if {[llength $argv] != 10} {
        error "usage: workspace boot mailbox frame sealed request reply jpeg packets timeout_ms"
    }
    lassign $argv workspace boot mailbox frame sealed request reply jpeg packets timeout
    set workspace [file normalize $workspace]
    foreach name {boot mailbox frame sealed timeout} {set $name [expr {[set $name]}]}
    if {$boot ni {0 1} || $timeout < 1000 || $timeout > 500000 ||
        $mailbox < 0x100000 || $mailbox + 128 > 0x40000000 || $mailbox % 64 ||
        $frame < 0x100000 || $frame + 65600 > 0x40000000 || $frame % 64 ||
        $sealed < 0x100000 || $sealed + 68096 > 0x40000000 || $sealed % 64 ||
        [file size $request] != 128 || [file exists $reply] ||
        [file exists $jpeg] || [file exists $packets]} {
        error "Invalid G3 owned DDR request/arguments"
    }
    connect -url tcp:127.0.0.1:3121
    if {$boot} {
        targets -set -filter {name == "APU"}
        rst -system -stop
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        source "$workspace/g3_camera/_ide/psinit/ps7_init.tcl"
        ps7_init
        targets -set -filter {name == "xc7z020"}
        fpga -file "$workspace/g3_camera/_ide/bitstream/m01.bit"
        targets -set -filter {name =~ "*Cortex-A9*#0"}
        ps7_post_config
        rst -processor
        dow -clear "$workspace/g3_camera/build/g3_camera.elf"
        con
        puts "G3_BOOT_OK"
    }
    targets -set -filter {name == "APU"}
    set start [clock milliseconds]
    while {[lindex [mrd -address-space AP0 -value $mailbox] 0] != 0x33474345} {
        if {[clock milliseconds] - $start > 10000} {error "G3 boot timeout"}
        after 100
    }
    set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
    if {$state == 1 || $state == 4} {error "G3 job already active"}
    mwr -address-space AP0 -bin -file $request $mailbox 32
    mwr -address-space AP0 [expr {$mailbox+4}] 1
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$mailbox+4}]] 0]
        if {$state == 2 || $state == 3} {break}
        if {[clock milliseconds] - $start > $timeout} {error "G3 command timeout"}
        after 50
    }
    mrd -address-space AP0 -bin -file $reply $mailbox 32
    if {$state != 2} {
        set status [lindex [mrd -address-space AP0 -value [expr {$mailbox+12}]] 0]
        set n [lindex [mrd -address-space AP0 -value [expr {$mailbox+16}]] 0]
        if {$n >= 4 && $n <= 65536} {
            mrd -address-space AP0 -bin -file $jpeg $frame [expr {($n+3)/4}]
            mrd -address-space AP0 -bin -file $packets $sealed 17024
        }
        disconnect
        error "G3 board job failed status=$status; inspect mailbox"
    }
    set n [lindex [mrd -address-space AP0 -value [expr {$mailbox+16}]] 0]
    set chunks [lindex [mrd -address-space AP0 -value [expr {$mailbox+20}]] 0]
    set sealed_length [lindex [mrd -address-space AP0 -value [expr {$mailbox+24}]] 0]
    set got_frame [lindex [mrd -address-space AP0 -value [expr {$mailbox+32}]] 0]
    set got_sealed [lindex [mrd -address-space AP0 -value [expr {$mailbox+36}]] 0]
    if {$n < 4 || $n > 65536 || $chunks != ($n + 1399) / 1400 ||
        $sealed_length != $n + 16 * $chunks || $sealed_length > 66288 ||
        $got_frame != $frame || $got_sealed != $sealed} {
        error "G3 completed lengths/addresses invalid"
    }
    mrd -address-space AP0 -bin -file $jpeg $frame [expr {($n+3)/4}]
    mrd -address-space AP0 -bin -file $packets $sealed [expr {($sealed_length+3)/4}]
    disconnect
    puts "G3_JOB_DONE frame=$n chunks=$chunks sealed=$sealed_length"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
