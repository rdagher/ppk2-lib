# Recipes

Four jobs people use a PPK2 for, done from a script.

## Flashing a DUT powered by the PPK2

A DUT that gets its power from the PPK2 is off until a command
switches it on, and its debug port does not answer. To flash it, power
it for the time the programmer runs:

```sh
ppk2 run --source --vdd 3.0 -- west flash
```

`ppk2 run` switches power on, runs the command after `--`, and
switches power off when it ends. It exits with the command's exit code,
so it fits in a Makefile, a `just` recipe or a CI job. Add
`--out flash.csv` to record while the programmer runs.

To flash from another terminal, or to debug, hold the power on until
Ctrl-C:

```sh
ppk2 power on --source --vdd 3.0 --hold
```

The same from Python:

```python
import subprocess

from ppk2 import Mode, Session, find_ppk2

with Session.open(find_ppk2().device) as session:
    session.set_mode(Mode.SOURCE)
    session.set_source_voltage(3000)
    session.power_on()  # the power is up about 1 ms later
    code = subprocess.run(["west", "flash"]).returncode
raise SystemExit(code)
```

An nRF chip stays in debug mode after it is flashed and draws about
1 mA more until it is power-cycled. Measure with a fresh `ppk2 capture`,
which power-cycles it, not inside the session that flashed.

## Current of a marked region

You want to know what one piece of firmware costs, a sensor read or a
radio transmission, and not the average over a whole capture. The PPK2
samples its digital inputs with every current sample. Raise a GPIO
while the code runs, and add up the current while the pin is high.

```c
gpio_set(MARK_PIN, 1);
read_sensor();
gpio_set(MARK_PIN, 0);
```

Wire the pin to `D0` of the logic port, with the port's `GND` and `VCC`
connected as in [getting started](getting-started.md#digital-inputs),
and capture as usual. The `D0` column of the file is 1 exactly while
the code ran.

The current of a region is the mean of its samples. One sample lasts
10 µs, so the charge of a region is the sum of its samples times 10 µs,
in microcoulombs. These are the figures the app shows for a selection:
average, max, time and charge.

```python
import pandas as pd

SAMPLE_S = 10e-6  # one sample lasts 10 µs

df = pd.read_csv("trace.csv", dtype={"D0-D7": str})
high = df["D0"] == 1
region = (high & ~high.shift(fill_value=False)).cumsum()  # counts the rising edges

regions = df[high].groupby(region[high])["Current(uA)"].agg(["size", "mean", "max", "sum"])
regions["duration_ms"] = regions["size"] * SAMPLE_S * 1e3
regions["charge_uC"] = regions["sum"] * SAMPLE_S  # µA × s = µC
print(regions[["duration_ms", "mean", "max", "charge_uC"]].round(2))
```

On the bench firmware of this repository, which keeps the CPU busy for
100 ms while D0 is high, the first rows are:

```text
    duration_ms     mean      max  charge_uC
D0
1         99.99  1380.27  2251.65     138.01
2         99.97  1381.59  2394.14     138.12
3         99.97  1380.31  2412.01     137.99
4        100.00  1381.19  2309.45     138.12
```

Over the 22 regions of that 5 s capture the mean current stayed between
1377.86 and 1381.59 µA.

Three things to watch:

- A capture can start or end in the middle of a region. Drop the first
  and the last row if they are cut.
- A lost sample is a row of 0.2 µA in the CSV, as in Nordic's app, so
  it lowers the mean and the sum. The summary at the end of a capture
  says whether any were lost.
- There is no energy here. The PPK2 measures current only. An energy
  is the charge times the voltage at the DUT, which you have to know
  from elsewhere: the voltage you set in Source meter mode, or one you
  measured in Ampere meter mode.

To get the numbers without a file, add up inside the capture callback:

```python
from ppk2 import Mode, Session, find_ppk2


class RegionCurrent:
    """Averages the current of each D0-high region; stops after ``wanted`` regions."""

    def __init__(self, wanted: int) -> None:
        self.wanted = wanted
        self.means_ua: list[float] = []
        self._inside = False
        self._sum_ua = 0.0
        self._count = 0

    def __call__(self, sample) -> bool:
        d0 = bool(sample.logic & 1)
        if d0 and not self._inside:
            self._inside, self._sum_ua, self._count = True, 0.0, 0
        if self._inside and d0:
            self._sum_ua += sample.current_micro_amps
            self._count += 1
        if self._inside and not d0:
            self._inside = False
            self.means_ua.append(self._sum_ua / self._count)
        return len(self.means_ua) < self.wanted


regions = RegionCurrent(wanted=10)
with Session.open(find_ppk2().device) as session:
    session.set_mode(Mode.AMPERE)
    session.set_source_voltage(3300)
    session.start_measuring()
    session.power_on()
    session.capture(regions)

mean = sum(regions.means_ua) / len(regions.means_ua)
print(f"{len(regions.means_ua)} regions, mean current {mean:.2f} µA")
```

```text
10 regions, mean current 1381.83 µA
```

## Long captures

The PPK2 sends 100,000 samples per second whatever the DUT does, so the
first question is the size of the file.

| Duration | Samples | CSV | `.ppk2` |
|---:|---:|---:|---:|
| 1 minute | 6 million | 240 MB | about 8 MB |
| 1 hour | 360 million | 14 GB | about 0.5 GB |
| 8 hours | 2.9 billion | 115 GB | about 4 GB |

The `.ppk2` column comes from the bench firmware of this repository; a
session file is compressed, so a noisier signal takes more. While it is
being written, a `.ppk2` capture uses 6 bytes per sample in a file next
to the output: 36 MB per minute, 17 GB for 8 hours.

```sh
ppk2 capture --out hour.ppk2 --seconds 3600
```

What to expect:

- The longest capture run for this release lasted two minutes. Nothing
  in the program depends on the duration, but hours-long captures have
  not been run, and a session file of several gigabytes has not been
  tried, here or in the app.
- Ctrl-C stops the capture and completes the file. A CSV always ends on
  a complete row. A `.ppk2` file appears complete or not at all.
- When the computer does not keep up, samples are lost. The capture
  warns once 500 are missing and gives the total at the end. The trace
  keeps its true length.
- The rate cannot be lowered at the PPK2. To keep fewer values, average
  blocks of samples afterwards: `ppk2 convert` accepts a CSV reduced to
  a power of ten, such as 1,000 samples per second.

## Comparing two firmware builds

You changed something and want to know whether the current went down.
Capture the same workload before and after, and compare the files.

1. Fix everything except the firmware: the same DUT, wiring, `--vdd`
   and duration. Whatever you leave free ends up in the comparison.
2. Capture the first build: `ppk2 capture --out before.csv --seconds 60`.
3. Flash the second build.
4. Capture again, to `after.csv`.

A checkout of the repository has a script that compares the two and
writes a report:

```sh
uv run --group validation python -m validation.compare_cli before.csv after.csv \
    --label-a before --label-b after --skip-initial-s 1 --out report.md
```

It reports the mean of each file and the Kolmogorov-Smirnov (KS)
statistic between the two distributions: 0 when they are the same, 1
when they do not overlap.

Know how much two identical runs differ before you read a difference
as a result. In the [validation](../validation/results.md), two
captures of the same firmware taken four minutes apart differ by 0.05 %
on the current of a marked region. At a few µA the spread can be
larger. Measure the spread of your own bench with two runs of one
build, and trust only differences well above it.

Two more cautions:

- A capture that starts at power-on contains the boot, which differs
  from one power cycle to the next. `--skip-initial-s` leaves it out.
- The mean says how much, not how. For a workload made of bursts,
  mark them with a GPIO and compare
  [region by region](#current-of-a-marked-region).
