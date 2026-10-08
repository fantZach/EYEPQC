set origin_dir [file normalize [file join [file dirname [info script]] ..]]
set out_dir [file join $origin_dir build keccak_ooc]
file mkdir $out_dir
create_project -force keccak_ooc $out_dir -part xc7z020clg400-2
read_verilog -sv [file join $origin_dir src rtl crypto keccak_round.sv]
read_verilog -sv [file join $origin_dir src rtl crypto keccak_f1600.sv]
read_verilog -sv [file join $origin_dir src rtl crypto keccak_sponge.sv]
synth_design -top keccak_sponge -part xc7z020clg400-2 -mode out_of_context
create_clock -name clk -period 10.000 [get_ports clk]
report_utilization -file [file join $out_dir utilization.rpt]
report_timing_summary -file [file join $out_dir timing.rpt]
write_checkpoint -force [file join $out_dir keccak_sponge_ooc.dcp]
puts "KECCAK_OOC_SYNTH_PASS"
exit
