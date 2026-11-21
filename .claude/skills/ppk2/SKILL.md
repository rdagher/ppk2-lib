---
name: ppk2
description: Drive a Nordic PPK2 with the ppk2 command or library. Find the device, capture current and digital inputs in Ampere meter or Source meter mode, power the DUT while it is flashed. Use when working with PPK2 hardware or power measurements in this repo.
---

# ppk2

This package is experimental: check options against `ppk2 --help`
before relying on them.

## Rules

- Only one program can hold the PPK2. If Nordic's Power Profiler app is
  open, captures fail with `DataPortNotFound`. Close the app first.
- Begin with `ppk2 list`. It shows each PPK2's USB serial and whether
  each port is `data`, `idle` or `busy`.
- Exit codes: 1 for a device or session error with a one-line message,
  2 for a usage error, 130 after Ctrl-C. `ppk2 run` returns the
  command's code (127 not found, 128+N killed by signal N).
- Power to the device under test (DUT) ends with the command. The PPK2
  cuts it when its port closes. Only `ppk2 power on --hold` or a
  running `ppk2 run` keeps a DUT up.
- Use Nordic's names: Ampere meter mode, Source meter mode, DUT,
  digital inputs (D0 to D7, on the logic port), supply voltage.
- Settings (`--user-gain`, `set_spike_filter`, `set_voltage_limit`,
  `set_user_gain`) go before `start_measuring()`. Nothing survives a
  session except the PPK2's own voltage and mode.

## Capture

```sh
ppk2 capture --out trace.csv --seconds 30                       # Ampere meter mode
ppk2 capture --source --vdd 3.0 --out trace.csv --seconds 30    # Source meter mode: the PPK2 powers the DUT
ppk2 capture --out trace.ppk2 --seconds 30                      # a file in the app's .ppk2 format
ppk2 convert trace.csv trace.ppk2                               # the same, from a CSV
```

A capture switches the DUT on as it starts, so the boot is at the start
of the file, about 10 ms in. The CSV has the 11 columns of the app's
export,
`Timestamp(ms),Current(uA),D0-D7,D0..D7`, with D0 the leftmost
character of `D0-D7`, at 100,000 samples per second. In Ampere meter
mode `--vdd` feeds the calibration: give the DUT's real supply voltage.

Digital inputs: on the logic port, D0 to D7 to GPIOs, `GND` to the
DUT's ground, `VCC` to the DUT's VDD.

## Flash a DUT powered through the PPK2

Until a command switches power on, the DUT is off and its debug port
does not answer.

```sh
ppk2 run --source --vdd 3.0 -- west flash    # power it for one command
ppk2 power on --source --vdd 3.0 --hold      # or hold it, and flash from another shell
```

In Ampere meter mode, drop `--source`. After flashing, an nRF chip stays in
debug mode and draws about 1 mA more until it is power-cycled. A
capture power-cycles it.

## Bench notes

- nRF52840 DK: measure with SW6 on "nRF only". Otherwise the interface
  chip adds about 85 mA.
- nRF54L15 and nRF54LM20 DKs: PPK2 in series at the current-measurement
  header. The nRF54LM20 DK idled at about 4 µA with everything
  connected; the nRF54L15 DK has not been measured.
- Idle currents drift between captures. Compare a signal with two
  levels region by region, not over the whole trace
  ([`validation/README.md`](../../../validation/README.md)).

## From Python

```python
from ppk2 import Mode, Session, find_ppk2

with Session.open(find_ppk2().device) as session:
    session.set_mode(Mode.AMPERE)        # or Mode.SOURCE
    session.set_source_voltage(3000)     # mV
    session.start_measuring()
    session.power_on()
    session.capture(lambda sample: keep_going)   # returning False ends the capture
```

The callback is the only way out of `capture`: it must return `False`
at some point. More in
[`docs/use/architecture.md`](../../../docs/use/architecture.md) and
[`docs/measure/protocol.md`](../../../docs/measure/protocol.md).

## Compare two captures

```sh
just compare-cli A.csv B.csv        # statistics of two captures, side by side
just cross-validate BIN_A BIN_B     # capture with two binaries, then compare
```

It passes when the headers are identical, the means are within 1 % and
the KS statistic is below 0.05.
