# All writes are to volatile PS/PL and the ELF-owned mailbox. No storage writes.
if {[catch {
    if {[llength $argv] != 4} {error "usage: workspace request.bin reply.bin mailbox_address"}
    lassign $argv workspace request reply address
    set workspace [file normalize $workspace]
    set address [expr {$address}]
    set job_size [expr {524288 + 76}]
    set job_words [expr {$job_size / 4}]
    if {$address < 0x100000 || $address + $job_size > 0x40000000 || $address % 64} {
        error "Mailbox is not an aligned owned DDR address"
    }
    if {[file size $request] != $job_size || [file exists $reply]} {error "Invalid request/existing reply"}
    connect -url tcp:127.0.0.1:3121
    puts [targets]
    targets -set -filter {name == "xc7z020"}
    targets -set -filter {name == "APU"}
    rst -system -stop
    targets -set -filter {name =~ "*Cortex-A9*#0"}
    source "$workspace/aes_mvp/_ide/psinit/ps7_init.tcl"
    ps7_init
    puts "AES_MVP_PS_INIT_OK"
    targets -set -filter {name == "xc7z020"}
    fpga -file "$workspace/aes_mvp/_ide/bitstream/m01.bit"
    puts "AES_MVP_FPGA_OK"
    targets -set -filter {name =~ "*Cortex-A9*#0"}
    ps7_post_config
    rst -processor
    dow -clear "$workspace/aes_mvp/build/aes_mvp.elf"
    puts "AES_MVP_ELF_OK pc=[rrd pc] mailbox=[mrd -value $address]"
    con
    puts "AES_MVP_RUNNING"
    targets -set -filter {name == "APU"}
    after 1000
    set start [clock milliseconds]
    while {[lindex [mrd -address-space AP0 -value $address] 0] != 0x3150564d} {
        if {[clock milliseconds] - $start > 20000} {error "MVP boot/mailbox timeout"}
        after 100
    }
    mwr -address-space AP0 -bin -file $request $address $job_words
    mwr -address-space AP0 [expr {$address + 4}] 1
    set start [clock milliseconds]
    while {1} {
        set state [lindex [mrd -address-space AP0 -value [expr {$address + 4}]] 0]
        if {$state == 3} {
            error "MVP board failure status=[mrd -address-space AP0 -value [expr {$address + 8}]]"
        }
        if {$state == 2} {break}
        if {[clock milliseconds] - $start > 30000} {error "MVP encryption timeout"}
        after 100
    }
    mrd -address-space AP0 -bin -file $reply $address $job_words
    disconnect
    puts "AES_MVP_JTAG_OK"
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
