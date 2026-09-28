# Read EARLY, before native scoped CDC constraints; PCLK maximum 72 MHz.
create_clock -period 13.888 -name cam_pclk [get_ports cam_pclk]
