# Changelog

## 0.1.0 — first experimental release (2026-08)

Initial public release. Library + CLI, one install.

### Protocol layer (`ppk2.protocol`, stdlib-only)

- Opcode table with wire-byte semantics documented per member.
- Metadata parser: indexed per-range keys (`R0`…`UG4`),
  chunk-tolerant accumulation, strict calibration-field
  validation (missing → `MissingField`, unparseable or
  non-finite → `InvalidValue`), soft defaults for the two
  runtime-state keys (VDD, mode).
- Sample decoder for the 4-byte word (14-bit ADC, 3-bit range,
  6-bit counter, 8 logic channels).
- Calibration formula matching Nordic's `getAdcResult`
  term-for-term; regression-pinned against a captured device.
- Stream parser: 4-byte alignment with cross-read remainder,
  counter-resync with corruption buffering and NaN data-loss
  placeholders, GUI noise-floor clamp, post-range-change EMA
  spike filter with tunable knobs (`SpikeFilter`).

### Client layer (`ppk2.client`)

- Probe-based discovery: VID/PID filter (`1915:c00a`), data-port
  identification by metadata probe, `list_ppk2s` with per-VCOM
  status, exclusive serial opens.
- `Session` context manager: recover-and-negotiate handshake
  with retry/backoff, source + ammeter modes, DUT power FET
  control with boot-inclusive t=0 capture support, host-side
  per-range user gain, host-enforced voltage limit ceiling,
  spike-filter configuration, data-loss notification hook.

### CLI (`ppk2`)

- `list`, `discover`, `metadata`, `power on|off [--hold]`,
  `capture`, `run -- <cmd>`, `version`.
- GUI-parity 11-column CSV output (byte-format-identical to the
  Nordic Power Profiler's export).
- `--source/--vdd` modes, `--serial`/`--port` selection,
  repeatable `--user-gain RANGE:GAIN`.
- Deterministic exit codes: device/session errors → 1 with a
  one-line stderr message, usage errors → 2, SIGINT → 130,
  `run` propagates the child's code (127 not-found, 128+N
  signal-killed).

### Validation & bench

- [`validation/`](validation/): port-agnostic A/B capture comparison harness
  (schema, sample rate, current statistics, KS test, per-pin
  duty/edge rates) with a pass/fail acceptance contract.
- [`firmware/bench-dut/`](firmware/bench-dut/): reference Zephyr DUT (D0 5 Hz,
  D1 0.5 Hz) for the nRF52840, nRF54L15, and nRF54LM20 DKs —
  hexes built with `just hex` or by the CI firmware matrix.
- Cross-validated on live hardware against the Nordic Power
  Profiler GUI — noise floor KS 0.0002, workload-region KS
  ≤ 0.014, per-region energy within 0.31 % (see the committed
  comparison rounds under
  [`validation/evidence/`](validation/evidence/)).

### Known limitations

- Experimental API — breaking changes possible between 0.x.
- Sync only (no asyncio surface).
- Windows: fast-tier tested, not yet bench-validated.
- Trigger-mode protocol not implemented (sampling mode only).
