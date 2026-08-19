# Validation

Two port-agnostic tools for comparing GUI-parity CSV captures against
any other ppk2-compatible binary (or against a Nordic Power Profiler
GUI export).

## `compare_cli.py`

Diff two CSVs and emit a Markdown report. Works on any pair of
GUI-parity CSVs — captures from this CLI, captures from another
ppk2-compatible binary, exports from the Nordic GUI.

```sh
uv run --group validation python -m validation.compare_cli path/to/a.csv path/to/b.csv \
    --label-a "this build" --label-b "GUI baseline" \
    --out report.md
```

Reports cover: header byte-equality, sample rate, current mean/std/max,
two-sample Kolmogorov–Smirnov on the current distributions, per-pin
duty cycle and rising-edge rate. Exits 0 if the acceptance contract
passes:

- Headers byte-identical
- Mean-current Δ within ±1 %
- KS statistic < 0.05

## `cross_validate.py`

Capture from two binaries back-to-back, then run `compare_cli` on the
results. Useful for any A/B validation — this project's `ppk2` against
another ppk2-compatible CLI, two builds of this project, or against a
reference binary you trust.

Run as a module from the repo root (mirrors the `just cross-validate`
recipe; a by-path invocation would fail to import `validation.compare_cli`):

```sh
uv run --group validation python -m validation.cross_validate \
    --binary-a $(which ppk2) \
    --binary-b /path/to/other/ppk2 \
    --label-a "this build" --label-b "other build" \
    --seconds 60
```

## What you need on the bench

A PPK2 plugged into the host, plus a DUT wired to it (ammeter mode
during these captures — the harness doesn't toggle the regulator).
Both binaries must accept `<binary> capture --out PATH --seconds N`
with the same semantics — the GUI-parity 11-column CSV output is
documented in `docs/PROTOCOL.md` (§ CSV format).

## Acceptance contract origin

The ±1 % mean-current and KS < 0.05 thresholds match the committed
GUI-parity comparison rounds (`validation/evidence/noise_floor_gui/`);
they're tight enough to
catch real calibration drift and loose enough that natural
sample-to-sample variation between two independent captures of the
same workload doesn't trip the test.

**Caveat — the ±1 % mean gate assumes an active workload.** It was
calibrated on a DUT whose mean (~38 µA) was dominated by
deterministic periodic bursts. Two situations break that assumption:

- **Boot-inclusive captures** (the capture path starts at FET-on, so
  the DUT's boot inrush is in the trace): the inrush is a
  per-power-cycle physical event, and at idle-level currents it can
  dominate the mean. Trim it with `--skip-initial-s 2` before
  gating.
- **Idle-level DUTs** (tens of µA steady): same-binary replicate
  runs on this bench differ by ~2-3 % in steady-state mean (thermal
  drift, regulator settling, power-cycle history). Measured
  2026-07-10: two back-to-back captures with the identical binary
  gave steady means of 18.14 vs 17.70 µA (Δ 2.5 %). At that scale,
  calibrate `--mean-tolerance-pct` from a same-binary replicate
  pair, or gate on the deterministic invariants (headers, KS,
  per-pin duty + edge rates) and treat the mean as informational.

The byte-level proof of implementation agreement is this repo's
parity fixture (`tests/protocol/test_stream.py` + `tests/fixtures/`)
— two implementations that pass it produce identical output for
identical input; capture-level deltas beyond it measure the bench,
not the code.
