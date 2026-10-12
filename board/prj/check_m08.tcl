set repo [file normalize [file join [file dirname [info script]] .. ..]]
if {[llength $argv] != 1} {error "usage: check_m08.tcl fresh-output-directory"}
set out [file normalize [lindex $argv 0]]
if {[file exists $out]} {error "Use a fresh output directory: $out"}
file mkdir $out
if {[llength [get_parts -quiet xc7z020clg400-2]] != 1} {error "Zynq-7000 part missing"}
foreach source {aes_sbox aes_inv_sbox aes_key_mem aes_encipher_block aes_decipher_block aes_core} {
    read_verilog [file join $repo board src rtl crypto secworks_aes ${source}.v]
}
read_verilog -sv [file join $repo board src rtl common axis_byte_packer.sv]
foreach source {gf128_mul ghash aes_gcm_encrypt aes_gcm_regs aes_gcm_axis} {
    read_verilog -sv [file join $repo board src rtl crypto ${source}.sv]
}
synth_design -top aes_gcm_axis -part xc7z020clg400-2 -mode out_of_context
create_clock -name aclk -period 10 [get_ports aclk]
report_utilization -file [file join $out utilization.txt]
report_timing_summary -file [file join $out timing.txt]
write_checkpoint [file join $out aes_gcm_axis.dcp]
puts "M08_SYNTH_OK $out (100 MHz OOC estimate, not board timing)"
