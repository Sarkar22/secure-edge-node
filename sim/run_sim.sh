#!/usr/bin/env bash
# Functional verification of the secure edge-inference node (iverilog).
# Bit-exact check of {ciphertext, class, probability} vs model/node_model.py.
set -e
cd "$(dirname "$0")"

# (re)generate consts + vectors from the golden model first
python3 ../model/node_model.py

iverilog -g2012 -I ../rtl -o sim.vvp \
    ../rtl/node_top.sv \
    ../rtl/cordic_activation.sv \
    ../rtl/simon_enc.sv \
    ../tb/node_tb.sv

vvp sim.vvp
