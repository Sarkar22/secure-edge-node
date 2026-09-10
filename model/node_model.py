#!/usr/bin/env python3
"""
Bit-accurate golden model for the SECURE EDGE-INFERENCE NODE.

Pipeline (one small FPGA datapath), streaming SIMON-CTR secure inference:
    feature (x0,x1) -> MLP[2-8-1]  -> class + probability
                       (MVM + tanh)   (MVM + sigmoid)
                    -> pack telemetry record (128 bit)
                    -> ciphertext = record XOR keystream          (CTR mode)
       where       keystream = SIMON128/128(key, counter)         (counter = nonce||seq)

Design intent for the paper (application-driven co-design):
  * The MLP is the SAME 2-8-1 two-moons classifier validated in
    cordic-activation/model/nn_experiment.py (we reuse its trained weights so the
    task accuracy carries over -- the node reaches the ideal fixed-point accuracy).
  * Activations = zero-DSP CORDIC; cipher = zero-DSP SIMON. ONLY the MVM uses a
    multiplier -> the whole secure node needs a SINGLE DSP (measured).
  * CTR mode is the key idea: the keystream = SIMON(counter) depends only on the
    counter, NOT on the inference result, so it is precomputed WHILE the MVM/CORDIC
    still classify. Encryption then collapses to a 1-cycle 128-bit XOR -> the block
    cipher latency is HIDDEN behind the inference (free in latency), and the node is
    a real streaming endpoint (fresh counter per record) rather than a single block.
  * All arithmetic is PURE INTEGER fixed point, identical to the RTL, so the chain is
    bit-exact: CORDIC and SIMON are already proven bit-exact; this fixes the MVM MAC.

Emits:
  rtl/node_consts.svh   weights/biases (Q.WF), SIMON key + CTR nonce, layout, widths.
  tb/node_vectors.hex   x0 x1 seq -> expected {ciphertext, class, prob} (streaming).
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOLO = os.path.dirname(ROOT)
sys.path.insert(0, os.path.join(SOLO, "cordic-activation", "model"))
sys.path.insert(0, os.path.join(SOLO, "simon-cipher", "model"))

import numpy as np
import cordic_model as cm          # bit-exact CORDIC tanh/sigmoid (matches the RTL)
import simon_model  as sm          # bit-exact SIMON encrypt (matches the RTL)
import nn_experiment as nx         # the validated 2-8-1 two-moons MLP (trained weights)

# ----------------------------------------------------------------- formats ----
cm.set_config(16, 16)             # full-precision CORDIC = the shipped cordic_consts.svh
IO_W, IO_F = cm.IO_W, cm.IO_F      # Q2.12
QF   = 1 << IO_F                    # 4096
WW, WF = 18, 12                    # weight format  Q(WW-WF).WF  (signed)
BW     = 32                        # bias width (fraction = IO_F+WF = 24)
ACCW   = 40                        # MAC accumulator width
HID    = 8                         # hidden neurons
PROD_F = IO_F + WF                 # product fraction bits (24); MAC shifts by WF -> Q2.12
NODE_KEY = 0x0f0e0d0c0b0a09080706050403020100   # official SIMON128/128 test key
CTR_NONCE = 0xA5A5A5A5A5A5A5A5A5A5A5A5           # 96-bit device nonce (CTR prefix)

def counter_block(seq):
    """CTR counter = 96-bit nonce || 32-bit record sequence (unique per record)."""
    return ((CTR_NONCE << 32) | (seq & 0xFFFFFFFF)) & ((1 << 128) - 1)

# clamp ranges on the pre-activations (match nn_experiment.quantize_arg)
TANH_LO, TANH_HI = -(1 << IO_F),  (1 << IO_F)          # +/-1.0
SIG_LO,  SIG_HI  = -(1 << (IO_W-1)), (1 << (IO_W-1))-1 # +/-2.0 (int14)

# ------------------------------------------------------ reuse trained weights -
# Reproduce nn_experiment.main()'s RNG sequence exactly: make_moons() then
# train_mlp() consume nx.RNG in the same order, so we get identical weights.
X, y = nx.make_moons()
ntr  = int(0.7 * len(X))
Xtr, ytr, Xte, yte = X[:ntr], y[:ntr], X[ntr:], y[ntr:]
W1f, b1f, W2f, b2f = nx.train_mlp(Xtr, ytr)            # (2,8) (8,) (8,1) (1,)

def qw(v): return int(round(float(v) * (1 << WF)))     # weight  -> Q.WF code
def qb(v): return int(round(float(v) * (1 << PROD_F))) # bias    -> Q.PROD_F code

W1c = [[qw(W1f[d][o]) for o in range(HID)] for d in range(2)]
W2c = [qw(W2f[h][0]) for h in range(HID)]
B1c = [qb(b1f[o]) for o in range(HID)]
B2c = qb(b2f[0])

# sanity: constants fit their declared widths
for d in range(2):
    for o in range(HID):
        assert -(1 << (WW-1)) <= W1c[d][o] < (1 << (WW-1)), "W1 overflow -> widen WW"
for h in range(HID):
    assert -(1 << (WW-1)) <= W2c[h] < (1 << (WW-1)), "W2 overflow -> widen WW"
for c in B1c + [B2c]:
    assert -(1 << (BW-1)) <= c < (1 << (BW-1)), "bias overflow -> widen BW"

# ------------------------------------------------------- fixed-point inference -
def _round_shift(acc):                 # Q.PROD_F -> Q2.12, round half up (== RTL)
    return (acc + (1 << (WF-1))) >> WF

def _clamp(v, lo, hi): return lo if v < lo else (hi if v > hi else v)

def to_code(xf):                       # float feature -> Q2.12 code
    return _clamp(int(round(xf * QF)), -(1 << (IO_W-1)), (1 << (IO_W-1)) - 1)

def infer(x0, x1):
    """x0,x1: Q2.12 integer codes. Returns (z1[8], a1[8], z2, prob, cls)."""
    z1 = []
    for o in range(HID):
        acc = B1c[o] + x0 * W1c[0][o] + x1 * W1c[1][o]
        z1.append(_clamp(_round_shift(acc), TANH_LO, TANH_HI))
    a1 = [cm.eval_tanh(z) for z in z1]                 # CORDIC tanh (Q2.12)
    acc = B2c + sum(a1[h] * W2c[h] for h in range(HID))
    z2 = _clamp(_round_shift(acc), SIG_LO, SIG_HI)
    prob = cm.eval_sigmoid(z2)                          # CORDIC sigmoid (Q2.12, [0,1])
    cls  = 1 if prob >= (1 << (IO_F-1)) else 0          # threshold at 0.5
    return z1, a1, z2, prob, cls

def pack_record(x0, x1, prob, cls, seq=0):
    """128-bit telemetry record (LSB-first): x0|x1|prob|class|seq|pad."""
    m14 = lambda v: v & 0x3FFF
    rec = (m14(x0)
           | (m14(x1)  << 14)
           | (m14(prob) << 28)
           | ((cls & 1) << 42)
           | ((seq & 0xFFFFFFFF) << 43))
    return rec & ((1 << 128) - 1)

def node(x0, x1, seq=0):
    """Full node: feature codes -> (class, prob, ciphertext) via SIMON-CTR."""
    _, _, _, prob, cls = infer(x0, x1)
    rec = pack_record(x0, x1, prob, cls, seq)
    ks  = sm.encrypt(NODE_KEY, counter_block(seq), 64, 2, 68, 2)   # keystream=SIMON(ctr)
    ct  = rec ^ ks                                                 # CTR: XOR (1-cycle)
    return cls, prob, ct, rec

# ------------------------------------------------------------ self-check -------
def selfcheck():
    codes = [(to_code(p[0]), to_code(p[1])) for p in Xte]
    preds = [infer(c0, c1)[4] for (c0, c1) in codes]
    acc = float(np.mean(np.array(preds) == (yte > 0.5)))
    pf  = nx.forward_float(Xte, (W1f, b1f, W2f, b2f))
    acc_float = float(np.mean((pf > 0.5) == (yte > 0.5)))
    print(f"[node_model] fixed-point node test accuracy = {acc*100:.2f}%  "
          f"(float MLP {acc_float*100:.2f}%, ideal fixed-pt 94.58%)")
    # show one worked example
    c0, c1 = codes[0]
    cls, prob, ct, rec = node(c0, c1)
    print(f"[node_model] example: x=({c0},{c1}) -> class={cls} prob={prob}/4096 "
          f"({prob/QF:.3f})\n             record=0x{rec:032x}\n             ct    =0x{ct:032x}")
    return acc

# ------------------------------------------------------- emit RTL constants ----
def _sv_signed(width, v):
    return (f"-{width}'sd{-v}" if v < 0 else f"{width}'sd{v}")

def emit_consts():
    p = os.path.join(ROOT, "rtl", "node_consts.svh")
    L = []
    A = L.append
    A("// AUTO-GENERATED by model/node_model.py -- do not edit by hand.")
    A("// Weights/biases for the 2-8-1 two-moons MLP (reused from cordic-activation).")
    A(f"localparam int FX_W = {IO_W};")
    A(f"localparam int FX_F = {IO_F};")
    A(f"localparam int WW   = {WW};")
    A(f"localparam int WF   = {WF};")
    A(f"localparam int BW   = {BW};")
    A(f"localparam int ACCW = {ACCW};")
    A(f"localparam int HID  = {HID};")
    A(f"localparam int TANH_LO = {TANH_LO};")
    A(f"localparam int TANH_HI = {TANH_HI};")
    A(f"localparam int SIG_LO  = {SIG_LO};")
    A(f"localparam int SIG_HI  = {SIG_HI};")
    A(f"localparam logic [127:0] NODE_KEY  = 128'h{NODE_KEY:032x};")
    A(f"localparam logic [95:0]  CTR_NONCE = 96'h{CTR_NONCE:024x};")
    # indexable ROMs (tiny -> distributed LUT ROM, zero BRAM)
    A("logic signed [WW-1:0] W1 [0:2*HID-1];   // [d*HID + o]")
    A("logic signed [WW-1:0] W2 [0:HID-1];")
    A("logic signed [BW-1:0] B1 [0:HID-1];")
    A("logic signed [BW-1:0] B2;")
    A("initial begin")
    for d in range(2):
        for o in range(HID):
            A(f"  W1[{d*HID+o}] = {_sv_signed(WW, W1c[d][o])};")
    for h in range(HID):
        A(f"  W2[{h}] = {_sv_signed(WW, W2c[h])};")
    for o in range(HID):
        A(f"  B1[{o}] = {_sv_signed(BW, B1c[o])};")
    A(f"  B2    = {_sv_signed(BW, B2c)};")
    A("end")
    open(p, "w").write("\n".join(L) + "\n")
    print(f"[node_model] wrote {os.path.relpath(p, ROOT)}")

# --------------------------------------------------------- emit test vectors ---
def emit_vectors(n=48):
    p = os.path.join(ROOT, "tb", "node_vectors.hex")
    pts = [(to_code(a), to_code(b)) for a, b in Xte[:n]]
    pts += [(0, 0), (4095, 4095), (-4096, -4096), (8191, -8192)]  # corners
    L = ["// x0 x1 seq ciphertext class prob   (all hex; streaming CTR, seq increments)"]
    for seq, (c0, c1) in enumerate(pts):
        cls, prob, ct, _ = node(c0, c1, seq)
        L.append(f"{c0 & 0x3FFF:04x} {c1 & 0x3FFF:04x} {seq:08x} {ct:032x} "
                 f"{cls:01x} {prob & 0x3FFF:04x}")
    open(p, "w").write("\n".join(L) + "\n")
    print(f"[node_model] wrote {os.path.relpath(p, ROOT)}  ({len(pts)} streaming vectors)")

if __name__ == "__main__":
    selfcheck()
    emit_consts()
    emit_vectors(len(Xte))      # all test-set inferences + corner cases
