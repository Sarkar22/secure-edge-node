# synth_node.tcl -- synth+impl the integrated secure edge-inference node (OOC).
#   vivado -mode batch -source synth/synth_node.tcl -tclargs <part> <period_ns>
set part   [lindex $argv 0]
set period [lindex $argv 1]
set root   [pwd]
set outdir $root/results/synth
file mkdir $outdir

read_verilog -sv $root/rtl/node_top.sv
read_verilog -sv $root/rtl/cordic_activation.sv
read_verilog -sv $root/rtl/simon_enc.sv
# wide 128-bit ciphertext port -> out-of-context (package has too few pins otherwise)
synth_design -top node_top -part $part -include_dirs $root/rtl -mode out_of_context \
             -flatten_hierarchy rebuilt
create_clock -period $period -name clk [get_ports clk]
opt_design
place_design
route_design

report_utilization    -file $outdir/utilization.rpt
report_utilization    -hierarchical -file $outdir/utilization_hier.rpt
report_timing_summary -file $outdir/timing.rpt
report_power          -file $outdir/power.rpt

proc ncells {pat} { return [llength [get_cells -hierarchical -filter "REF_NAME =~ $pat"]] }
proc ncells_in {sub pat} {
    return [llength [get_cells -hierarchical -filter "REF_NAME =~ $pat && NAME =~ *$sub*"]]
}
set luts [ncells LUT*]; set ff [ncells FD*]; set dsp [ncells DSP48*]
set bram [ncells RAMB*]; set srl [ncells SRL*]
# DSP breakdown: confirm activation + cipher are DSP-free, MVM holds the only DSP
set dsp_act [ncells_in u_act DSP48*]
set dsp_enc [ncells_in u_enc DSP48*]
set dsp_mvm [expr {$dsp - $dsp_act - $dsp_enc}]

set wns [get_property SLACK [get_timing_paths -setup -max_paths 1 -nworst 1]]
if {$wns eq ""} { set wns 0.0 }
set fmax [expr {($period-$wns) > 0 ? 1000.0/($period-$wns) : 0.0}]
set power "NA"
if {[catch {
    set fh [open $outdir/power.rpt r]; set txt [read $fh]; close $fh
    if {[regexp {Total On-Chip Power \(W\)\s*\|\s*([0-9.]+)} $txt -> p]} { set power $p }
}]} {}

set csv $root/results/node_synth.csv
set fh [open $csv w]
puts $fh "part,period_ns,lut,ff,dsp,dsp_mvm,dsp_act,dsp_enc,bram,srl,wns_ns,fmax_mhz,power_w"
puts $fh [format "%s,%s,%d,%d,%d,%d,%d,%d,%d,%d,%.3f,%.1f,%s" \
          $part $period $luts $ff $dsp $dsp_mvm $dsp_act $dsp_enc $bram $srl $wns $fmax $power]
close $fh
puts "==== node : LUT=$luts FF=$ff DSP=$dsp (mvm=$dsp_mvm act=$dsp_act enc=$dsp_enc)"
puts "==== BRAM=$bram SRL=$srl WNS=$wns Fmax=${fmax}MHz Power=${power}W"
