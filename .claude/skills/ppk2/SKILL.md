---
name: ppk2
description: Drive a Nordic PPK2 power profiler with the ppk2-lib CLI/library — discover devices, capture current+logic traces (source or ammeter mode), flash a DUT powered through the PPK2, and attribute energy to firmware regions via GPIO trace markers. Use when working with PPK2 hardware, power measurements, or energy attribution in this repo.
---

# ppk2 — capture, flash, attribute

> **Experimental repo.** APIs may change between 0.x versions.
> Verify claims against `--help` and the docs before relying on them.

## Ground rules

- One process owns the PPK2 at a time (exclusive serial open). If the
  Nordic Power Profiler GUI is running, captures fail with
  `DataPortNotFound` — quit the GUI first (or pass `--port`).
- Start every session with `ppk2 list` — shows each PPK2's USB serial
  and per-VCOM status (`data` / `idle` / `busy`).
- Exit codes: device/session errors → 1 (one-line stderr), usage → 2,
  Ctrl-C → 130, `ppk2 run` propagates the child's code (127 = not
  found, 128+N = signal-killed).
- All configuration (`--user-gain`, library `set_spike_filter`,
  `set_voltage_limit`, `set_user_gain`) must happen **before**
  `start_measuring()`; nothing persists across sessions except the
  firmware's VDD + mode.

## Capture

```sh
# Ammeter mode (PPK2 in series with the DUT's supply):
ppk2 capture --out trace.csv --seconds 30

# Source mode (PPK2 supplies the DUT):
ppk2 capture --source --vdd 3.0 --out trace.csv --seconds 30
```

Captures are boot-inclusive: the DUT power-cycles at t=0, so boot
inrush lands at the start of the file. Output is the Nordic GUI's
11-column CSV (`Timestamp(ms),Current(uA),D0-D7,D0..D7`, D0 leftmost
in the bit string, 100 kSPS). In ammeter mode `--vdd` still matters:
it feeds the calibration formula's VDD term — set it to the DUT's
real rail voltage.

## Flash a DUT powered through the PPK2

The PPK2's output switch defaults open → the DUT is dark and SWD is
dead ("debug port unavailable" errors). Two recipes:

```sh
ppk2 run --source --vdd 3.0 -- west flash          # one-shot
ppk2 power on --source --vdd 3.0 --hold            # hold in shell 1,
# flash from shell 2, Ctrl-C to release
```

Ammeter mode: same recipes without `--source`. After flashing,
nRF chips stay in debug-interface mode (~1 mA extra) until a power
cycle — `ppk2 capture`'s built-in power cycle clears it.

## Energy attribution (trace markers)

[`firmware/trace-demo/`](../../../firmware/trace-demo/) is the worked example: firmware brackets code
regions with GPIO markers wired to the PPK2's logic port
([`include/ppk2_trace.h`](../../../firmware/trace-demo/include/ppk2_trace.h) C API,
[`include/ppk2_trace.hpp`](../../../firmware/trace-demo/include/ppk2_trace.hpp) C++ RAII
guard), then:

```sh
python firmware/trace-demo/attribute.py trace.csv --vdd 3.0
```

reports per-region energy (D0/D1-marked pulses, sleep floor).
Wiring: logic-port D0/D1 to the marker pins, **GND to DUT ground and
VCC to the DUT's VDD rail** (VCC is the logic-threshold reference).

## Bench specifics worth knowing

- nRF52840 DK: measure with SW6 = "nRF only" (else ~85 mA of
  interface-MCU floor); LEDs are disconnected in that position.
- nRF54L15/LM20 DKs: PPK2 in series at the current-measurement
  header; board routing configured via Nordic's Board Configurator
  app; µA-scale floors with everything connected.
- Idle-floor comparisons between separate captures drift (thermal);
  compare duty-cycled signals per-region, not full-trace
  (see [`validation/README.md`](../../../validation/README.md) and
  [`validation/evidence/`](../../../validation/evidence/)).

## Library (Python)

```python
from ppk2 import Session, Mode, find_ppk2

with Session.open(find_ppk2().device) as s:
    s.set_mode(Mode.AMPERE)          # or Mode.SOURCE
    s.set_source_voltage(3000)       # mV
    s.start_measuring()
    s.power_on()
    s.capture(lambda sample: keep_going)   # False stops the loop
```

The capture callback must eventually return False — it is the loop's
only exit. Layers: `ppk2.protocol` (stdlib-only wire primitives),
`ppk2.client` (pyserial driver), `ppk2.cli`. Details:
[`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md),
[`docs/PROTOCOL.md`](../../../docs/PROTOCOL.md).

## Validation harness

```sh
just compare-cli A.csv B.csv        # statistical diff of two captures
just cross-validate BIN_A BIN_B     # capture with two binaries + diff
```

Acceptance contract: headers byte-identical, mean Δ ±1 %, KS < 0.05
(calibrated for steady signals — condition on regions for
duty-cycled ones).
