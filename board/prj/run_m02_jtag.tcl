# Volatile PS/PL probe only. No ELF, storage, network or image capture.
if {[catch {
    if {[llength $argv] < 1 || [llength $argv] > 3} {
        error "usage: xsdb run_m02_jtag.tcl <M02 hardware directory> ?sensor reset count 1..20? ?expect failure 0|1?"
    }
    set hw [file normalize [lindex $argv 0]]
    set sensor_resets 20
    if {[llength $argv] >= 2} {set sensor_resets [lindex $argv 1]}
    set expect_failure 0
    if {[llength $argv] == 3} {set expect_failure [lindex $argv 2]}
    if {![string is integer -strict $sensor_resets] || $sensor_resets < 1 || $sensor_resets > 20} {
        error "sensor reset count must be an integer from 1 through 20"
    }
    if {$expect_failure ni {0 1} || ($expect_failure && $sensor_resets != 1)} {
        error "expected-failure mode requires expect failure 1 and exactly one sensor reset"
    }
    set bit [file join $hw m01.runs impl_1 system_wrapper.bit]
    set init [file join $hw m01.gen sources_1 bd system ip system_ps7_0 ps7_init.tcl]
    foreach path [list $bit $init [file join $hw m01.xsa]] {
        if {![file isfile $path]} {error "Missing fresh M02 artifact: $path"}
    }
    connect -url tcp:127.0.0.1:3121
    puts [targets]
    targets -set -filter {name == "APU"}
    rst -system -stop
    targets -set -filter {name =~ "*Cortex-A9*#0"}
    source $init
    ps7_init
    targets -set -filter {name == "xc7z020"}
    fpga -file $bit
    targets -set -filter {name =~ "*Cortex-A9*#0"}
    ps7_post_config
    targets -set -filter {name == "APU"}
    set base 0x41200000
    mwr -address-space AP0 [expr {$base+4}] 0
    mwr -address-space AP0 [expr {$base+12}] 0xffffffff
    # These are sensor RESET/PWDN cycles within one JTAG session, not board power cycles.
    for {set run 0} {$run < $sensor_resets} {incr run} {
        set full_sweep [expr {$sensor_resets == 20}]
        set vts [expr {$full_sweep && $run == 19 ? 2400 : 1968}]
        set quality [expr {$full_sweep && $run == 19 ? 12 : 1}]
        set high_resolution [expr {$full_sweep && $run >= 10}]
        set cfg [expr {($vts << 9) | ($quality << 3) | ($high_resolution << 2) | 2}]
        mwr -address-space AP0 $base [expr {$cfg | 0x80000000}]
        after 10
        mwr -address-space AP0 $base $cfg
        after 1
        mwr -address-space AP0 $base [expr {$cfg | 1}]
        after 1
        mwr -address-space AP0 $base $cfg
        set begin [clock milliseconds]
        while {1} {
            set status [lindex [mrd -address-space AP0 -value [expr {$base+8}]] 0]
            if {$status & 0x00030000} {break}
            if {[clock milliseconds]-$begin > 5000} {error "M02 probe polling timeout"}
            after 10
        }
        mwr -address-space AP0 $base [expr {$cfg | 0x40000000}]
        set detail [lindex [mrd -address-space AP0 -value [expr {$base+8}]] 0]
        mwr -address-space AP0 $base $cfg
        puts [format "M02_RESULT run=%d size=%s quality=%d vts=%d status=%08X id=%04X last=%04X error=%d" \
            $run [expr {$high_resolution ? "640x480" : "320x240"}] $quality $vts $status \
            [expr {$status & 0xffff}] [expr {$detail & 0xffff}] [expr {($status >> 24) & 15}]]
        if {$expect_failure} {
            if {($status & 0x00020000) == 0 || ($status & 0x00010000) != 0 ||
                ($status & 0x00040000) != 0 || ($status & 0x00800000) != 0 ||
                (($status >> 24) & 15) == 0} {
                error "M02 expected failure did not remain fail-closed"
            }
        } elseif {($status & 0x00030000) != 0x00010000 || ($status & 0xffff) != 0x5640 ||
            ($status & 0x0f000000) != 0 || !($status & 0x00800000)} {error "M02 camera configuration failed"}
    }
    if {$expect_failure} {
        set final_error [expr {($status >> 24) & 15}]
        puts "M02_JTAG_EXPECTED_FAILURE sensor_resets=1 configured=0 capture_resetn=0 failed=1 error=$final_error status=[format %08X $status]"
    } else {
        puts "M02_JTAG_OK sensor_resets=$sensor_resets (board cold-boot and DVP/JPEG capture still pending)"
    }
    disconnect
} message options]} {
    puts stderr [dict get $options -errorinfo]
    catch {disconnect}
    exit 1
}
