# Getting started

From nothing to a first capture: install, wire, check, capture, read.

## Install

ppk2-lib is not on PyPI yet. Install it from the repository:

```sh
pip install "git+https://github.com/rdagher/ppk2-lib"
```

This gives you the `ppk2` command and the `ppk2` Python package. You
need Python 3.11 or newer. Two dependencies come with it, `pyserial`
and `typer`; there is nothing to compile.

```console
$ ppk2 version
0.1.0
```

In a project of your own, add it as a dependency, here with `uv`:

```sh
uv add "git+https://github.com/rdagher/ppk2-lib"
```

What it has been tested on:

| | Linux | macOS | Windows |
|---|---|---|---|
| Unit tests, Python 3.11 and 3.13 | yes | yes | yes |
| Tests with a PPK2 on a bench | no | yes, macOS 26 | no |

So Linux and Windows are expected to work but have not measured
anything yet.

## Wire the PPK2

Wire it as you would for the Power Profiler app. The PPK2 has two
modes, named here as in the app, and the wiring decides which one you
use.

### Ampere meter mode

The DUT has its own supply and the PPK2 sits in series with it. This is
the default.

```text
  supply  ──────►  VIN  ┐
                        │ PPK2 measures the current passing through
  DUT VDD ◄──────  VOUT ┘
  DUT GND ───────  GND
```

- `--vdd` sets nothing in this mode, but the calibration uses it. Give
  the voltage the DUT really runs at. The default is 3.3. The
  [measurement principle](../measure/principle.md#why-the-supply-voltage-matters)
  says how much a wrong value costs.
- Nothing else may feed the DUT. Current that reaches it by a second
  path does not pass through the PPK2 and is not measured.
- Nordic's dev kits have a current-measurement header for this: remove
  the jumper and put the PPK2 across it, `VIN` on the supply side.

### Source meter mode

The PPK2 supplies the DUT. Add `--source`, and `--vdd` becomes the
supply voltage, from 0.8 to 5.0 V.

```text
  DUT VDD ◄──────  VOUT    PPK2 supplies and measures
  DUT GND ───────  GND
```

The PPK2 can supply up to 1 A. Nordic's user guide asks for a second
USB cable, in the `USB POWER ONLY` socket, above 400 mA.

A DUT powered this way is off until a command switches it on, and off
again when the command ends: the PPK2 cuts power when its serial port
closes.

### Digital inputs

The logic port has eight digital inputs, `D0` to `D7`, sampled together
with the current. They are optional. To use them, connect:

- the signals you want to see to `D0` to `D7`;
- the logic port's `GND` to the DUT's ground;
- the logic port's `VCC` to the DUT's VDD. The PPK2 uses it as the
  reference to tell high from low.

## Check the PPK2

Only one program can hold a PPK2, so quit the app first.

```console
$ ppk2 list
PPK2  serial=A1B2C3D4E5F6
  /dev/cu.usbmodemA1B2C3D4E5F62   [data port]
  /dev/cu.usbmodemA1B2C3D4E5F64   [idle]
```

A PPK2 has two serial ports and only one carries data. `ppk2 list`
shows which, and marks a port `busy` when another program holds it.
With several PPK2s attached, add `--serial A1B2C3D4E5F6` to any
command.

```console
$ ppk2 metadata
Calibrated: false
HW:         46575
IA:         60
VDD:        3300 mV
mode:       2 (Source meter)
R : [    1.002119e+03,     1.014783e+02,     1.033613e+01,     9.682840e-01,     5.643343e-02]
...
```

This is the calibration the PPK2 reports, plus the voltage and mode it
was left in. Nordic's documentation gives the LED as breathing blue in
Ampere meter mode and breathing red in Source meter mode.

!!! note "`Calibrated: false` is normal"

    It does not mean the readings are wrong. See
    [the `Calibrated` flag](../measure/principle.md#the-calibrated-flag).

## Capture

In Ampere meter mode, the default:

```sh
ppk2 capture --out idle.csv --seconds 30
```

In Source meter mode, with the PPK2 powering the DUT at 3.3 V:

```console
$ ppk2 capture --out first.csv --seconds 5 --source --vdd 3.3
opening session (Source meter mode, vdd=3300 mV)
capturing 5.00 s -> first.csv (Ctrl-C to stop early)
  [  1.0s]      109569 samples  mean  868.11 µA
  [  2.0s]      209921 samples  mean  786.69 µA
  [  3.0s]      310273 samples  mean  758.06 µA
  [  4.0s]      410625 samples  mean  743.30 µA
captured 509952 samples over 5.00 s (101954 Hz)
```

Progress goes to the terminal and the samples go to the file. Ctrl-C
stops early and keeps what was recorded.

A capture switches the DUT on as it starts and off as it ends, so the
boot is in the file. The file begins about 0.1 s before the power comes
up, which is why this one holds 5.1 s of samples and the summary shows
more than 100,000 Hz. The
[known caveats](../measure/protocol.md#10-known-caveats) have the
measurements.

## Read the file

The CSV has the 11 columns of the app's export, one row every 0.01 ms:

```csv
Timestamp(ms),Current(uA),D0-D7,D0,D1,D2,D3,D4,D5,D6,D7
0,0.000,00000000,0,0,0,0,0,0,0,0
0.01,0.000,00000000,0,0,0,0,0,0,0,0
0.02,0.000,00000000,0,0,0,0,0,0,0,0
```

A quick look with numpy:

```python
import numpy as np

t_ms, ua = np.loadtxt("first.csv", delimiter=",", skiprows=1, usecols=(0, 1), unpack=True)
print(f"{len(ua)} samples over {t_ms[-1] / 1000:.2f} s")
print(f"mean {ua.mean():.2f} µA, max {ua.max():.0f} µA")
```

```text
509952 samples over 5.10 s
mean 735.02 µA, max 142873 µA
```

[File formats](../measure/formats.md) has the columns in detail.

## Open it in the app

A name ending in `.ppk2` gives a session file in the format the app
saves and loads, and `ppk2 convert` makes one from a CSV:

```console
$ ppk2 convert first.csv first.ppk2
wrote first.ppk2: 509952 samples at 100000 S/s (5.10 s)
```

Here the CSV is 20.5 MB and the session file 0.7 MB.
[File formats](../measure/formats.md#how-far-this-is-checked) says how
far this format has been checked.

## Notes per system

### macOS

The two ports are `/dev/cu.usbmodem*`.

### Linux

The ports are `/dev/ttyACM*`. Your user must be allowed to open them,
which usually means joining the `dialout` group:

```sh
sudo usermod -a -G dialout $USER    # then log out and back in
```

Some distributions use `uucp` instead. `ls -l /dev/ttyACM0` shows the
group.

### Windows

The PPK2 shows up as two COM ports. `ppk2 power on --hold` and Ctrl-C
handling in `ppk2 run` use POSIX calls that Windows does not have.

## Notes on Nordic dev kits

- nRF52840 DK: measure with switch SW6 on "nRF only". Otherwise the
  interface chip stays on the measured supply and adds about 85 mA.
- nRF54L15 DK and nRF54LM20 DK: put the PPK2 across the
  current-measurement header. With everything else left connected, the
  nRF54LM20 DK idled at about 4 µA.
- After flashing, an nRF chip stays in debug mode and draws about 1 mA
  more until it is power-cycled. A capture power-cycles it.

## Next

- [The `ppk2` command](command.md): every command and option.
- [Recipes](recipes.md): flashing, the energy of a marked region, long
  captures, comparing two builds.
- [Measurement principle](../measure/principle.md): what the numbers
  are.
