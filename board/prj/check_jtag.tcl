# Enumerate/select debug targets only. No reset, register/memory access, or download.
if {[catch {
    connect -url tcp:127.0.0.1:3121
    puts "JTAG_TARGETS"
    puts [targets]
    targets -set -filter {name == "xc7z020"}
    targets -set -filter {name == "APU"}
    targets -set -filter {name =~ "*Cortex-A9*#0"}
    disconnect
    puts "JTAG_CHECK_OK APU Cortex-A9#0 xc7z020"
} message options]} {
    puts stderr "JTAG_CHECK_FAILED $message"
    catch {disconnect}
    exit 1
}
