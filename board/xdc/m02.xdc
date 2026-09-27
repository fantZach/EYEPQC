# Baseboard V3.9 P2 + official camera44 XDC, LVCMOS33 module interface.
# External R110/R111 = 4.7k pullups; SCCB outputs are open-drain.
set_property -dict {PACKAGE_PIN T10 IOSTANDARD LVCMOS33} [get_ports cam_scl]
set_property -dict {PACKAGE_PIN T11 IOSTANDARD LVCMOS33} [get_ports cam_sda]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports cam_resetn]
set_property -dict {PACKAGE_PIN V15 IOSTANDARD LVCMOS33} [get_ports cam_pwdn]
# Async SCCB pins enter two-stage synchronizers. Don't mask their second stage.
set_false_path -from [get_ports {cam_scl cam_sda}] -to [get_pins -hier -regexp {.*(scl_sync_reg|sda_sync_reg|scl_status_sync_reg|sda_status_sync_reg)\[0\]/D}]
# Slow camera controls/SCCB are not synchronous data outputs relative to FCLK.
set_false_path -to [get_ports {cam_scl cam_sda cam_resetn cam_pwdn}]
# W15/P2.17 XCLK intentionally unconnected: module oscillator not yet verified.
