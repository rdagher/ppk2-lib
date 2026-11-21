# Recipes

Four jobs people use a PPK2 for, done from a script.

## Flash a DUT powered by the PPK2

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

## Energy of a marked region

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

One sample lasts 10 µs. Its charge is its current times 10 µs, and its
energy is that charge times the supply voltage:

```python
import pandas as pd

SAMPLE_S = 10e-6  # one sample lasts 10 µs
VDD = 3.3  # volts at the DUT

df = pd.read_csv("trace.csv", dtype={"D0-D7": str})
high = df["D0"] == 1
pulse = (high & ~high.shift(fill_value=False)).cumsum()  # counts the rising edges

pulses = df[high].groupby(pulse[high])["Current(uA)"].agg(["size", "mean", "sum"])
pulses["duration_ms"] = pulses["size"] * SAMPLE_S * 1e3
pulses["energy_uJ"] = pulses["sum"] * SAMPLE_S * VDD  # µA × s × V = µJ
print(pulses[["duration_ms", "mean", "energy_uJ"]].round(2))
```

On the bench firmware of this repository, which keeps the CPU busy for
100 ms while D0 is high, the first rows are:

```text
    duration_ms     mean  energy_uJ
D0
1        100.00  1387.25     457.79
2        100.00  1386.73     457.62
3        100.00  1387.30     457.81
4        100.00  1386.41     457.51
```

Over the 22 regions of that 5 s capture the energy stayed between
456.71 and 457.81 µJ.

Three things to watch:

- A capture can start or end in the middle of a region. Drop the first
  and the last row if they are cut.
- A lost sample has no row in the CSV, so it is missing from the sum.
  The summary at the end of a capture says whether any were lost.
- Energy needs the voltage the DUT really ran at. In Ampere meter mode,
  measure it and use it both for `--vdd` and for `VDD` above.

To get the numbers without a file, add up inside the capture callback:

```python
from ppk2 import Mode, Session, find_ppk2

SAMPLE_S = 10e-6  # one sample lasts 10 µs
VDD = 3.3  # volts at the DUT


class RegionEnergy:
    """Adds up the energy of each D0-high region; stops after ``wanted`` regions."""

    def __init__(self, wanted: int) -> None:
        self.wanted = wanted
        self.energies_uj: list[float] = []
        self._inside = False
        self._sum_ua = 0.0

    def __call__(self, sample) -> bool:
        d0 = bool(sample.logic & 1)
        if d0 and not self._inside:
            self._inside, self._sum_ua = True, 0.0
        if self._inside and d0:
            self._sum_ua += sample.current_micro_amps
        if self._inside and not d0:
            self._inside = False
            self.energies_uj.append(self._sum_ua * SAMPLE_S * VDD)
        return len(self.energies_uj) < self.wanted


regions = RegionEnergy(wanted=10)
with Session.open(find_ppk2().device) as session:
    session.set_mode(Mode.AMPERE)
    session.set_source_voltage(int(VDD * 1000))
    session.start_measuring()
    session.power_on()
    session.capture(regions)

mean = sum(regions.energies_uj) / len(regions.energies_uj)
print(f"{len(regions.energies_uj)} regions, mean {mean:.2f} µJ")
```

```text
10 regions, mean 456.98 µJ
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

## Compare two firmware builds

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
as a result. Two captures of the same firmware, 5 s each, taken one
after the other on the bench of this repository, gave means 0.31 %
apart and a KS statistic of 0.0204. At a few tens of µA the spread is
larger: two identical runs of an idle DUT differed by 2 to 3 %. Measure
the spread of your own bench with two runs of one build, and trust only
differences well above it.

Two more cautions:

- A capture that starts at power-on contains the boot, which differs
  from one power cycle to the next. `--skip-initial-s` leaves it out.
- The mean says how much, not how. For a workload made of bursts,
  mark them with a GPIO and compare
  [region by region](#energy-of-a-marked-region).
