# Secure edge-inference node — design notes

A single small-FPGA datapath that (1) classifies a 2-D feature vector with a tiny
neural network and (2) encrypts the resulting telemetry record before transmission.
It composes three already-verified blocks; the only *new* logic is the MVM datapath
and the top-level FSM.

## Dataflow (streaming SIMON-CTR, latency-hidden crypto)
```
(x0,x1) Q2.12 ─▶ MVM L1 (2→8) ─▶ z1 ─▶ CORDIC tanh ─▶ a1 ─▶ MVM L2 (8→1) ─▶ z2
        ─▶ CORDIC sigmoid ─▶ (prob,class) ─▶ pack 128-b record ─┐
                                                                XOR ─▶ ciphertext
   counter(nonce‖seq) ─▶ SIMON128/128 ─▶ keystream (precomputed) ─┘
```

## Why this is interesting (the pitch)
- The **activations** (`cordic_activation`) and the **cipher** (`simon_enc`) are
  **zero-DSP / zero-BRAM**. The ONLY multiplier in the whole node is the shared MVM
  MAC, so a complete *secure inference* endpoint needs **a single DSP** — every other
  DSP on the device stays free for the host application.
- **CTR latency hiding (the co-design):** keystream = SIMON(counter) is independent of the
  inference result, so SIMON is launched at accept time and runs **concurrently** with the
  MVM/CORDIC. Encryption is then a 1-cycle XOR → the ~70-cycle block-cipher latency is
  **hidden** behind the inference (measured: 111 hidden vs 181 blocking cyc, same RTL via
  the `HIDE_CRYPTO` param; both emit identical ciphertext).
- It is the SAME 2-8-1 two-moons MLP validated in `../cordic-activation` (numerically
  identical weights), so the task accuracy carries over: the hardware node reaches the
  **ideal fixed-point accuracy (94.58%)** — the integer MVM adds no accuracy loss.

## Reused / new
- **Reused (verified, provenance in the sibling projects):**
  `rtl/cordic_activation.sv` + `cordic_consts.svh` (from `../cordic-activation`),
  `rtl/simon_enc.sv` + `simon_consts.svh` (from `../simon-cipher`). Cite, do not re-claim.
- **New:** `rtl/node_top.sv` (MVM + FSM + integration), `model/node_model.py`
  (golden model), `tb/node_tb.sv`, synth/analysis scripts.

## Fixed-point contract (model == RTL, bit-exact)
- Features / activations: **Q2.12** (14-bit signed), as in the CORDIC unit.
- Weights: **Q6.12** (18-bit signed, `WW=18,WF=12`); biases: 32-bit, fraction 24.
- MAC: one signed multiply/cycle, accumulate in 40 bits; product fraction = 24.
- Finalize: round half-up by `+2^11 >> 12` → Q2.12, then **saturate** to the
  activation's input range (tanh: ±1.0 = ±4096; sigmoid: ±2.0 = [−8192, 8191]).
- The CORDIC tanh/sigmoid and SIMON encrypt are already bit-exact to their models;
  `node_model.py` fixes the one new piece (the MAC) in pure integer arithmetic, so the
  full chain is bit-exact. Verified **244/244** (full two-moons test set + corners).

## 128-bit telemetry record (LSB-first)
| bits | field | bits | field |
|---|---|---|---|
| 13:0 | x0 (Q2.12) | 42 | class |
| 27:14 | x1 (Q2.12) | 74:43 | seq / nonce (32 b) |
| 41:28 | prob (Q2.12) | 127:75 | zero pad |

Encrypted with SIMON128/128 under a fixed key (the official test key, a placeholder for
a provisioned device key). `seq` is a placeholder for a real per-record nonce/counter.

## Control / latency
The FSM runs one inference at a time: `IDLE → L1MAC → L1ACT → L2MAC → L2ACT → PACK
→ FIN → DONE` (hidden mode; blocking mode inserts `ENC` before `FIN`). SIMON is kicked off
at accept and runs concurrently, so per-inference latency is **111 cycles** (hidden) vs
**181** (blocking) — the ~70-cycle cipher is fully overlapped. Throughput-oriented designs
would pipeline the stages; this node is latency/area-oriented for a sensor endpoint.

## Reproduce
```bash
cd secure-edge-node
bash sim/run_sim.sh                                   # regen consts/vectors + verify (244/244)
PART=xck26-sfvc784-2LV-c bash synth/run_synth.sh      # combined OOC place&route
/tmp/mplvenv/bin/python model/analyze.py              # budget + tables + figures
```
