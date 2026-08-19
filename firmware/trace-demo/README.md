# Zephyr trace-marker demo

A reference example for **energy attribution with the PPK2**: Zephyr
firmware brackets code regions with GPIO markers wired to the PPK2's
logic inputs, the `ppk2` CLI captures current + logic at 100 kSPS,
and `attribute.py` turns the CSV into per-region energy numbers.

Two tiny reusable headers do the firmware side:

| Header | Language | Surface |
|---|---|---|
| `include/ppk2_trace.h` | C (works from C++ too) | `ppk2_trace_init()`, `ppk2_trace_set(ch, on)` |
| `include/ppk2_trace.hpp` | C++17 | `ppk2::TraceScope` RAII guard, `ppk2::trace_scope(ch, lambda)` |

Drop them into any Zephyr app; the pins come from two `zephyr,user`
devicetree properties (see `boards/*.overlay`).

## What the demo firmware does

```
boot:   3 quick D0 pulses (C API)  — sync burst marking reset
sweep:  D1 high for the whole sweep (RAII)
          10 × [ D0 high: 600 ms busy-blink workload (RAII)
                 D0 low:  150 ms idle gap              ]
rest:   2 s idle, then the sweep repeats forever
```

The workload busy-waits (CPU awake), the gaps `k_sleep` (CPU idle),
so the current plateaus and valleys line up with the D0 marker — that
alignment is the whole demo.

## Boards

Same trace pins as `firmware/bench-dut/` — one wiring for both:

| Dev kit | Board target | D0 | D1 |
|---|---|---|---|
| nRF54LM20DK | `nrf54lm20dk/nrf54lm20b/cpuapp` | P1.12 | P1.13 |
| nRF54L15DK | `nrf54l15dk/nrf54l15/cpuapp` | P1.11 | P1.12 |
| nRF52840 DK | `nrf52840dk/nrf52840` | P0.28 (A2) | P0.29 (A3) |

Wiring, all from the PPK2's logic port: `D0`/`D1` to the pins
above, **`GND` to DK ground, and `VCC` to the DK's VDD rail** —
the logic-port VCC is the level reference the PPK2 uses for the
digital-input thresholds, so it must follow the DUT's I/O
voltage. Then put the PPK2 in the DUT's supply path (either mode
below).

### nRF52840 DK bench setup (reference scenario)

Powering via the PPK2 in source mode at 3.0 V, `VOUT` -> the P21
"External supply" header. Switch positions:

| Switch | Position | Why |
|---|---|---|
| SW8 (power) | ON | |
| SW9 (supply select) | VDD | take power from P21 |
| SW10 (VEXT -> nRF) | ON | enable the P21 input |
| SW6 | **nRF only** for measuring | isolates the interface-MCU section (~85 mA of parasitic floor in DEFAULT). Also disconnects LEDs/buttons. |

Two-position workflow: flip SW6 to DEFAULT once to *see* the LED
blink the workload pattern ("is it alive?"), then back to
**nRF only** to measure. In the measurement position the liveness
signal is the trace itself — D0 pulsing at ~1.3 Hz, D1 framing
each sweep — and the LED GPIO toggles into a disconnected load at
no cost. All reference captures on this DK are taken in
**nRF only**.

## Build + flash

Needs the Nordic NCS toolchain — the recipes use the
nrfutil-managed install at `/opt/nordic/ncs` (`NCS_VERSION`
selects the version, `NCS_WORKSPACE` overrides the path):

```sh
just build [BOARD]      # build/<dk>/merged.hex
just flash [BOARD]      # program via host nrfutil
```

### Flashing while the PPK2 powers the DUT (source mode)

If the DK's debugger is powered but the target rail comes from the
PPK2, the SWD port is dead until the rail is up. Two equivalent
recipes:

```sh
# A: hold VDD from a second shell for as long as you need
ppk2 power on --source --vdd 3.0 --hold     # shell 1 (Ctrl-C releases)
just flash                                  # shell 2

# B: one-shot — power the DUT just for the flash command
ppk2 run --source --vdd 3.0 -- just flash
```

In ammeter mode (DUT powered externally through the PPK2 shunt) the
rail is already up — `just flash` alone works; the capture below
will include whatever the flash did unless you reset first.

## Capture

```sh
# Source mode: PPK2 supplies 3.0 V and records from the DUT's reset
ppk2 capture --source --vdd 3.0 --out trace.csv --seconds 30

# Ammeter mode: PPK2 in series with an external supply
ppk2 capture --out trace.csv --seconds 30
```

`ppk2 capture` power-cycles the DUT at t=0 (boot-inclusive), so the
sync burst and the first sweep land at the start of the file. A
manual Nordic GUI capture started mid-run works too — the repeating
sweep plus the boot burst make alignment easy either way.

## Attribute energy

```sh
python attribute.py trace.csv --vdd 3.0
```

Prints per-workload (D0) and per-sweep (D1) energy — mean ± std and
region width — plus the idle-floor mean current. In source mode, pass
the same `--vdd` you captured with; in ammeter mode, your external
rail voltage.

Expected shape on a 30 s capture: ~3 sweeps, 10 workloads each,
workload energy orders of magnitude above the idle gaps (busy-wait
vs `k_sleep`).

### nRF54LM20DK bench setup (ammeter mode)

DK on USB (powers the board + J-Link); pull the current-measurement
jumper and put the PPK2 in series across that header (`VIN` supply
side, `VOUT` nRF side). Logic clips as in the pin table + `VCC` to a
VDD pin. Unlike the nRF52840 DK there is no isolation switch — the
DK is configured with Nordic's **Board Configurator** app (which can
keep LEDs connected, disable SWD, and so on). The reference numbers
below were taken with **everything connected** — LEDs, SWD, flash,
VCOMs all routed — and still reach the µA-scale sleep floor; no
isolation is needed on this DK.

With the PPK2 in series, its output switch defaults **open** — the
nRF is dark and SWD is dead until the path closes. Flash with the
one-shot recipe: `ppk2 run --vdd 3.3 -- just flash` (or hold with
`ppk2 power on --vdd 3.3 --hold` in a second shell).

## Reference results (bench-measured 2026-08)

nRF52840 DK cross-validated against a Nordic Power Profiler GUI
capture of the same signal (per-region energies agree within
0.3 %; see `validation/evidence/trace_demo/`).

| | nRF52840 DK (source 3.0 V) | nRF54LM20DK (ammeter, 3.3 V) |
|---|---|---|
| D0 workload (busy-blink) | 6 715 ± 20 µJ / 596.7 ms (≈3.75 mA) | 2 862 ± 4 µJ / 600.0 ms (≈1.45 mA) |
| D1 sweep (10 workloads + gaps) | 70.0 mJ / 7.47 s | 28.7 mJ / 7.50 s |
| sleep floor (k_sleep), median | ≈636 µA | **4.3 µA** |

GUI-vs-CLI parity plots for both boards (trace overlays + region
ECDFs) live in
[`validation/evidence/trace_demo/`](../../validation/evidence/trace_demo/README.md#parity-plots).

The nRF52840 floor is a PCA10056 board-level floor in this setup,
not the chip's capability — the same firmware reaches the µA floor
on the nRF54LM20 DK's dedicated measurement path (workload-to-floor
contrast there ≈340×).

## Reusing the headers in your app

1. Copy `include/ppk2_trace.h` (+ `.hpp` if C++) into your app.
2. Add the two `zephyr,user` GPIO properties to your board overlay
   (pick any two free pins; wire them to the PPK2's D0/D1).
3. `ppk2_trace_init()` once at boot, then mark regions:
   - C: `ppk2_trace_set(0, true); … ppk2_trace_set(0, false);`
   - C++: `ppk2::TraceScope mark{ppk2::D0};` in any scope.

Markers cost one GPIO write each (~sub-µs) and the PPK2 samples them
with every current sample, so attribution granularity is 10 µs.
