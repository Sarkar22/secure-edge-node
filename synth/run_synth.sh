#!/usr/bin/env bash
# Combined place&route of the secure edge-inference node on the KV260.
#   PART=xck26-sfvc784-2LV-c bash synth/run_synth.sh
set -e
cd "$(dirname "$0")/.."
PART="${PART:-xck26-sfvc784-2LV-c}"
PERIOD="${PERIOD:-2.0}"      # over-constrained; Fmax extracted from WNS
vivado -mode batch -source synth/synth_node.tcl -tclargs "$PART" "$PERIOD"
echo "---- results/node_synth.csv ----"
cat results/node_synth.csv
