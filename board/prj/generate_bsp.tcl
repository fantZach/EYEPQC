# Offline HSI flow: reads an XSA, generates sources, never connects to a board.
if {[catch {
    if {[llength $argv] ni {3 4}} {error "usage: generate_bsp.tcl <XSA> <fresh output> <embeddedsw repo> ?fsbl?"}
    lassign $argv xsa output repository boot
    set xsa [file normalize $xsa]
    set output [file normalize $output]
    if {![file isfile $xsa] || [file exists $output]} {error "Missing XSA or output already exists"}
    hsi set_repo_path [file normalize $repository]
    set hw [hsi open_hw_design $xsa]
    if {[common::get_property PART $hw] ne "xc7z020clg400-2"} {error "Unexpected target part"}
    set sw [hsi create_sw_design -proc ps7_cortexa9_0 -os standalone eye_bsp]
    hsi set_property CONFIG.stdin ps7_uart_0 [hsi get_os]
    hsi set_property CONFIG.stdout ps7_uart_0 [hsi get_os]
    if {$boot eq "fsbl"} {hsi add_library xilffs 5.6}
    hsi generate_bsp -dir $output -hw $hw -sw $sw
    if {$boot eq "fsbl"} {
        hsi generate_app -dir "[file dirname $output]/fsbl" -hw $hw -sw $sw -app zynq_fsbl
    }
    puts "EYEPQC_BSP_GENERATED $output"
    hsi close_hw_design $hw
} message options]} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
