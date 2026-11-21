# ppk2-lib

A Python library and command-line tool for Nordic's Power Profiler
Kit II (PPK2). The PPK2 measures the current of a device under test
(DUT) and samples eight digital inputs with it, 100,000 times per
second. With ppk2-lib a script, a terminal or a CI job drives it,
without the Power Profiler app.

This is an experimental release (0.1.0). It works and is checked on
hardware, but the API may still change between 0.x versions.

## Why it exists

The Power Profiler app is made for looking at a trace by hand. A
measurement worth making once is usually worth repeating: after every
change, on every board, in CI. That takes a command and a library, the
same ones at the desk and on the test bench, so that a number seen
during development is the number the pipeline checks.

## In a terminal

```console
$ ppk2 capture --out boot.csv --seconds 3 --source --vdd 3.3
opening session (Source meter mode, vdd=3300 mV)
capturing 3.00 s -> boot.csv (Ctrl-C to stop early)
  [  1.0s]      100191 samples  mean  947.46 µA
  [  2.0s]      199681 samples  mean  823.90 µA
  [  3.0s]      300033 samples  mean  781.88 µA
captured 301056 samples over 3.01 s (100099 Hz)
```

The PPK2 powers the DUT at 3.3 V, switches it on as the capture starts,
and writes the same CSV the app exports. A few more:

```sh
ppk2 capture --out idle.ppk2 --seconds 30    # a session file in the app's format
ppk2 power on --hold --source --vdd 3.3      # keep the DUT powered until Ctrl-C
ppk2 run --source --vdd 3.3 -- west flash    # power the DUT while it is flashed
```

## In a script

```python
from ppk2 import Mode, Session, find_ppk2

with Session.open(find_ppk2().device) as session:
    session.set_mode(Mode.AMPERE)
    session.start_measuring()
    session.power_on()
    session.capture(lambda sample: sample.current_micro_amps < 1000)
```

`capture` calls your function for every sample, 100,000 times per
second, and stops when it returns `False`. Here it stops at the first
sample of 1 mA or more.

## In CI

`ppk2 run` powers the DUT, records while a command runs, and exits
with that command's exit code. A test job can therefore record the
current of the very run it checks:

```sh
ppk2 run --source --vdd 3.3 --out tests.csv -- pytest tests/
```

A budget is then a few lines over the file:

```python
import numpy as np

ua = np.loadtxt("tests.csv", delimiter=",", skiprows=1, usecols=1)
assert ua.mean() < 2000, f"mean current {ua.mean():.0f} µA is over the budget"
```

The [recipes](use/recipes.md) go further: the current of one marked
piece of code, and comparing two builds.

## Three parts

This documentation answers three questions.

| Question | Part | Pages |
|---|---|---|
| How do I use it? | Using it | [Getting started](use/getting-started.md), [the `ppk2` command](use/command.md), [recipes](use/recipes.md), [architecture](use/architecture.md), [API reference](use/api.md), [troubleshooting](use/troubleshooting.md) |
| What exactly is measured, and how does one talk to a PPK2? | How it measures | [Measurement principle](measure/principle.md), [protocol](measure/protocol.md), [file formats](measure/formats.md) |
| Why believe the numbers? | Validation against Nordic's app | [Method](validation/method.md), [results](validation/results.md) |

If this is your first time, start with
[getting started](use/getting-started.md).

## What it is good for

- Sleep and idle currents. The lowest of the PPK2's five measurement
  ranges resolves 0.2 µA.
- Comparing two firmware builds: capture the same workload before and
  after a change and compare the files.
- The current of one piece of code: raise a GPIO around it and average
  the current while the pin is high.
- Powering a DUT from a script, for instance while it is flashed.
- Captures in the app's own formats: `ppk2` writes the CSV the app
  exports and its `.ppk2` session file.

The [recipes](use/recipes.md) show each of these.

## What it is not for

- Edges shorter than 10 µs. One sample lasts 10 µs.
- Accuracy beyond the PPK2's own. Nordic gives it as better than
  ±20 %, and ppk2-lib is checked against Nordic's app, not against a
  calibrated instrument.
- Voltage. The PPK2 measures current only.
- Looking around a trace by eye. The app's chart is the better tool:
  save a `.ppk2` file and open it there.

## Names

| What | Name |
|---|---|
| Distribution, what you install | `ppk2-lib` |
| Python package, what you import | `ppk2` |
| Command | `ppk2` |

The distribution has its own name because `ppk2-api` on PyPI is
another project, IRNAS's library.
