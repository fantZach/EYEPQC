# Official 1_led example: PL LED H15, bank powered at 3.3 V.
# FCLK0 is constrained by PS7; M01 does not use the U18 external oscillator.
set_property PACKAGE_PIN H15 [get_ports led]
set_property IOSTANDARD LVCMOS33 [get_ports led]
