# OOC internal clocks only; board DVP input/output delays belong to M05 integration.
# Read before XPM scoped constraints so they use real periods, not their 1000 ns fallback.
create_clock -name pclk -period 13.888 [get_ports pclk]
create_clock -name axis_clk -period 10 [get_ports axis_clk]
# XPM applies scoped CDC false paths/max-delay/bus-skew. Do not mask them with clock groups.
