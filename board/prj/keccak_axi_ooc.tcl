set origin_dir [file normalize [file join [file dirname [info script]] .. ..]]
set out_dir [file join $origin_dir build keccak_axi_ooc]
file mkdir $out_dir
create_project -force keccak_axi_ooc $out_dir -part xc7z020clg400-2
read_verilog -sv [file join $origin_dir board src rtl crypto keccak_round.sv]
read_verilog -sv [file join $origin_dir board src rtl crypto keccak_f1600.sv]
read_verilog -sv [file join $origin_dir board src rtl crypto keccak_axi_lite.sv]
synth_design -top keccak_axi_lite -part xc7z020clg400-2 -mode out_of_context
create_clock -name s_axi_aclk -period 10.000 [get_ports s_axi_aclk]
report_utilization -file [file join $out_dir utilization.rpt]
report_timing_summary -file [file join $out_dir timing.rpt]
write_checkpoint -force [file join $out_dir keccak_axi_lite_ooc.dcp]
puts "KECCAK_AXI_OOC_SYNTH_PASS"
exit
