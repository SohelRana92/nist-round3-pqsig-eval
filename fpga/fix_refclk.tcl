# fix_refclk.tcl - give the MIG its 200 MHz reference clock and build.
#
#   vivado -mode batch -nojournal -nolog -source fpga/fix_refclk.tcl -tclargs <CLK12MHZ pin>
#
# The Arty S7 MIG preset feeds sys_clk_i from the board's 100 MHz oscillator
# but leaves clk_ref_i (the IDELAYCTRL reference, 200 MHz) to the user. GUI
# connection automation turns it into a top-level port with no pin, and
# placement fails. This script removes that port and adds a Clocking Wizard
# that makes 200 MHz from the board's 12 MHz oscillator (pin from Digilent's
# Arty-S7-25-Master.xdc, passed as the argument). Nothing else changes.

if {[llength $argv] != 1} { puts "usage: -tclargs <CLK12MHZ package pin>"; exit 1 }
set clkpin [lindex $argv 0]
set h $env(HOME)
open_project [lindex [glob $h/pqsig-eval/build/gui/*/*.xpr] 0]
open_bd_design [get_files system.bd]

# 1. remove the unplaced clk_ref_i port
if {[llength [get_bd_ports -quiet clk_ref_i]]} {
    delete_bd_objs [get_bd_nets -quiet -of [get_bd_ports clk_ref_i]] [get_bd_ports clk_ref_i]
}

# 2. 12 MHz board clock -> Clocking Wizard -> 200 MHz MIG reference
if {![llength [get_bd_cells -quiet clk_wiz_0]]} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz clk_wiz_0
}
set_property -dict [list \
    CONFIG.PRIM_IN_FREQ {12.000} \
    CONFIG.PRIM_SOURCE {Single_ended_clock_capable_pin} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ {200.000} \
    CONFIG.USE_RESET {false} \
    CONFIG.USE_LOCKED {false}] [get_bd_cells clk_wiz_0]
if {![llength [get_bd_ports -quiet clk12mhz]]} {
    create_bd_port -dir I -type clk -freq_hz 12000000 clk12mhz
}
connect_bd_net [get_bd_ports clk12mhz] [get_bd_pins clk_wiz_0/clk_in1]
connect_bd_net [get_bd_pins clk_wiz_0/clk_out1] [get_bd_pins mig_7series_0/clk_ref_i]
puts "CLKWIZ_OUT_HZ: [get_property CONFIG.FREQ_HZ [get_bd_pins clk_wiz_0/clk_out1]]"

validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
make_wrapper -files [get_files system.bd] -top -force

# 3. pin of the 12 MHz clock, next to the marker constraint
set xdc [lindex [get_files -of [get_filesets constrs_1] *marker.xdc] 0]
set fh [open $xdc r]; set old [read $fh]; close $fh
if {[string first "clk12mhz" $old] < 0} {
    set fh [open $xdc a]
    puts $fh "set_property -dict { PACKAGE_PIN $clkpin IOSTANDARD LVCMOS33 } \[get_ports clk12mhz\]"
    close $fh
}

# 4. synthesis, implementation, bitstream
reset_run synth_1
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
puts "IMPL after: [get_property STATUS [get_runs impl_1]]"
if {![string match "*write_bitstream Complete*" [get_property STATUS [get_runs impl_1]]]} {
    puts "ERROR: implementation did not finish; see the run log"
    exit 1
}

# 5. hardware platform for Vitis, the design as a script, and the reports
write_hw_platform -fixed -include_bit -force $h/pqsig-eval/build/gui/pqsig_mb.xsa
write_bd_tcl -force $h/pqsig-eval/fpga/system_bd_s25.tcl
puts "UI_CLK_HZ: [get_property CONFIG.FREQ_HZ [get_bd_pins mig_7series_0/ui_clk]]"
open_run impl_1
report_utilization -file $h/pqsig-eval/build/gui/utilization.rpt
report_timing_summary -file $h/pqsig-eval/build/gui/timing.rpt
report_power -file $h/pqsig-eval/build/gui/power.rpt
puts "FINISHED"
exit
