---
name: ppk2
description: Drive a Nordic PPK2 with the ppk2 command or library. Find the device, capture current and digital inputs in Ampere meter or Source meter mode, power the DUT while it is flashed. Use when working with PPK2 hardware or power measurements in this repo.
---

# ppk2

This package is experimental: check options against `ppk2 --help`
before relying on them.

## Rules

- Only one program can hold the PPK2. If Nordic's Power Profiler app is
  open, a command fails with `error: could not identify the PPK2 data
  port` (`DataPortNotFound` from the library). Close the app first.
- Begin with `ppk2 list`. It shows each PPK2's USB serial and marks
  each port `[data port]`, `[idle]` or `[busy: ...]`. Add
  `--mask-serial` when the output goes into a screenshot or a report.
- Exit codes: 1 for an error, with one line starting with `error:`. A
  capture that ends with fewer samples than asked also exits 1. 2 is a
  usage error, and 130 follows Ctrl-C, except for
  `ppk2 power on --hold`, which returns 0. `ppk2 run` returns the
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
ppk2 capture --source --vdd 3.3 --out trace.csv --seconds 30    # Source meter mode: the PPK2 powers the DUT
ppk2 capture --out trace.ppk2 --seconds 30                      # a file in the app's .ppk2 format
ppk2 convert trace.csv trace.ppk2                               # the same, from a CSV
```

A capture switches the DUT on as it starts, so the boot is at the start
of the file, about 10 ms in. The CSV has the 11 columns of the app's
export,
`Timestamp(ms),Current(uA),D0-D7,D0..D7`, with D0 the leftmost
character of `D0-D7`, at 100,000 samples per second. In Ampere meter
mode `--vdd` feeds the calibration: give the DUT's real supply voltage.

A lost sample is a row of 0.2 µA with the digital inputs low, as in the
app's export. The summary line at the end of a capture counts them.

When a DUT wakes from sleep, the PPK2 can read tens of mA too high for
40 µs. For short events that repeat, compare the median of their
charge, not the mean
([Principle](../../../docs/measure/principle.md#limit-waking-from-sleep)).

Digital inputs: on the logic port, D0 to D7 to GPIOs, `GND` to the
DUT's ground, `VCC` to the DUT's VDD.

## Flashing a DUT powered through the PPK2

Until a command switches power on, the DUT is off and its debug port
does not answer.

```sh
ppk2 run --source --vdd 3.3 -- west flash    # power it for one command
ppk2 power on --source --vdd 3.3 --hold      # or hold it, and flash from another shell
```

In Ampere meter mode, drop `--source`. After flashing, an nRF chip
stays in debug mode and draws more until it is power-cycled: 330 µA
where it idles at 1.4 µA, on the nRF54LM20 DK. A capture power-cycles
the DUT, so measure with a fresh one.

## Bench notes

- nRF52840 DK: measure with SW6 on "nRF only". Otherwise the interface
  chip stays on the measured supply and hides the nRF52840's current.
- nRF54L15 and nRF54LM20 DKs: PPK2 in series at the current-measurement
  header. The nRF54LM20 DK idles at 1.4 µA with the bench firmware and
  everything connected; the nRF54L15 DK has not been measured.
- Idle currents drift between captures. Compare a signal with two
  levels region by region, not over the whole trace
  ([`validation/README.md`](../../../validation/README.md)).

## From Python

```python
import time

from ppk2 import Mode, Session, find_ppk2

samples = []

with Session.open(find_ppk2().device) as session:
    session.set_mode(Mode.AMPERE)        # or Mode.SOURCE
    session.set_source_voltage(3300)     # mV
    session.start_measuring()
    session.power_on()
    deadline = time.monotonic() + 1.0    # one second from power-on

    def on_sample(sample) -> bool:
        samples.append(sample.current_micro_amps)
        return time.monotonic() < deadline   # False ends the capture

    session.capture(on_sample, keep_going=lambda: time.monotonic() < deadline)

print(len(samples), "samples")
```

The callback ends `capture` by returning `False`. `keep_going` ends it
when the PPK2 sends nothing, a case in which the callback is never
called. More in
[`docs/develop/architecture.md`](../../../docs/develop/architecture.md) and
[`docs/measure/protocol.md`](../../../docs/measure/protocol.md).

## Comparing two captures

```sh
just compare-cli A.csv B.csv        # statistics of two captures, side by side
just cross-validate BIN_A BIN_B     # capture with two binaries, then compare
```

It passes when the headers are identical, the means are within 1 % and
the KS statistic is below 0.05.

The captures of the validation are not on `main`: `just captures`
fetches them from the branch `captures`.
