# Independent M03 synthesis only; no board programming or camera BRAM shortcut.
set check_top dvp_capture
set check_clock pclk
set check_period 13.888
set check_ooc 1
source [file join [file dirname [info script]] check_m02.tcl]
