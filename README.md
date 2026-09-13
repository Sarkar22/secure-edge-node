# Secure Edge-Inference Node (single-DSP, latency-hidden encryption)

A small MLP classifies a feature and its telemetry record is CTR-encrypted before transmission. Because the CTR keystream depends only on a counter, it is precomputed **during** the inference, so encryption costs no added latency. Activation and cipher are DSP-free, so the whole node uses exactly **one** DSP slice.

This is the artifact for a paper submitted to **IEEE CCECE 2027** (under review). Every
number below is reproduced by the scripts in this repository.

## Results

- **244/244** streaming vectors bit-exact (class, probability and ciphertext)
- Node accuracy 94.58%, identical to ideal fixed-point (integer MVM adds no loss)
- Latency 111 cycles hidden vs 181 blocking: **70 cycles (38.7%) removed**, identical ciphertext
- KV260: 2346 LUT / 2785 FF / **1 DSP** / 0 BRAM / 171.5 MHz
- sky130 ASIC: 0.516 mm², 18,933 cells, timing met, DRC clean and LVS clean

## Reproducing

```bash
bash sim/run_sim.sh   # regenerate constants/vectors and verify 244/244
```
```bash
PART=xck26-sfvc784-2LV-c bash synth/run_synth.sh   # place-and-route + per-block decomposition
```
```bash
python3 model/analyze.py   # budget, tables and figures
```

```bash
OPENLANE_DIR=/path/to/OpenLane DESIGN=node_top bash asic/run_asic.sh   # sky130 RTL-to-GDSII
```

The `asic/` directory holds the OpenLane configuration for each
signed-off configuration; the flow itself is third-party (see Requirements).

## Requirements

Third-party tools, not included here. Any recent version should work; these are what the
reported numbers were produced with.

| tool | used | purpose |
|---|---|---|
| Icarus Verilog | 12.0 | simulation (`iverilog -g2012`) |
| Python 3 | 3.12 + numpy (matplotlib for figures) | golden models and analysis |
| AMD Vivado | 2024.2 | FPGA synthesis and place-and-route |
| OpenLane | v1.0.2, sky130A PDK | open-source RTL-to-GDSII |

## Layout

```
model/    Python golden model: the executable specification, and the analysis scripts
rtl/      synthesizable SystemVerilog
tb/       self-checking testbenches
sim/      one-command verification
synth/    Vivado scripts (constraints, sweeps, reporting)
results/  measured CSVs and the figures generated from them
```

## Notes

`rtl/node_consts.svh` is **generated** by `model/node_model.py`; do not hand-edit it.

`rtl/cordic_activation.sv` and `rtl/simon_enc.sv` are reused verbatim from the two sibling projects in this account; provenance is recorded in `docs/DESIGN.md`.

CTR mode provides **confidentiality only**, not integrity. Authenticated encryption is addressed separately in [zero-shadow-aead](https://github.com/Sarkar22/zero-shadow-aead).

## License

MIT, see [LICENSE](LICENSE).
