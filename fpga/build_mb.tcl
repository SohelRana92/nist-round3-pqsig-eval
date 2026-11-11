# build_mb.tcl - rebuild the MicroBlaze system for the Digilent Arty S7-25
# in batch mode: bitstream, hardware platform (XSA) and reports.
#
#   vivado -mode batch -nojournal -source fpga/build_mb.tcl -tclargs build/fpga_s25
#
# The block design comes from fpga/system_bd_s25.tcl, which Vivado 2025.2
# wrote (write_bd_tcl) from the design built and verified on the board:
#   MIG 7-series DDR3 (256 MB at 0x80000000), board preset, sys_clk_i from
#     the 100 MHz oscillator; clk_ref_i (200 MHz) from a Clocking Wizard fed
#     by the 12 MHz oscillator CLK12MHZ (pin F14)
#   MicroBlaze v11.0 on the MIG ui_clk (81.25 MHz): 64 KB local memory,
#     16 KB I- and D-cache, barrel shifter, 64-bit multiplier, divider,
#     pattern compare, debug module
#   AXI UART Lite 115200 baud on the USB UART, AXI Timer in 64-bit mode,
#     AXI GPIO with one output, the energy marker, on Pmod JA pin 1 (L17)
# Pins come from Digilent's Arty-S7-25-Master.xdc. The design script checks
# that it runs in Vivado 2025.2.
#
# Results of the reference build (Vivado 2025.2): 10,617 LUTs, 26 BRAM,
# 4 DSP on the XC7S25; worst negative slack +1.316 ns. This batch script was
# run on 4 November 2026 and reproduced the GUI build: no errors or critical
# warnings, WNS +1.316 ns, WHS +0.055 ns, ui_clk 81,247,969 Hz.

if {[llength $argv] != 1} { puts "usage: -tclargs <out_dir>"; exit 1 }
set out  [file normalize [lindex $argv 0]]
set here [file dirname [file normalize [info script]]]

create_project pqsig_mb $out -part xc7s25csga324-1 -force
set_property board_part digilentinc.com:arty-s7-25:part0:1.1 [current_project]
source [file join $here system_bd_s25.tcl]

# Pins that the board preset does not set: the marker and the 12 MHz clock.
set xdc [file join $out pins.xdc]
set fh [open $xdc w]
puts $fh "set_property -dict { PACKAGE_PIN L17 IOSTANDARD LVCMOS33 } \[get_ports {GPIO_0_tri_o\[0\]}\]"
puts $fh "set_property -dict { PACKAGE_PIN F14 IOSTANDARD LVCMOS33 } \[get_ports clk12mhz\]"
close $fh
add_files -fileset constrs_1 $xdc

set bd [get_files system.bd]
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property top system_wrapper [current_fileset]

launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
if {![string match "*write_bitstream Complete*" [get_property STATUS [get_runs impl_1]]]} {
    puts "ERROR: implementation did not finish; see $out/pqsig_mb.runs/impl_1/runme.log"
    exit 1
}
write_hw_platform -fixed -include_bit -force [file join $out pqsig_mb.xsa]
open_run impl_1
report_utilization -file [file join $out utilization.rpt]
report_timing_summary -file [file join $out timing.rpt]
report_power -file [file join $out power.rpt]
puts "UI_CLK_HZ: [get_property CONFIG.FREQ_HZ [get_bd_pins mig_7series_0/ui_clk]]"
puts "done: [file join $out pqsig_mb.xsa]"
