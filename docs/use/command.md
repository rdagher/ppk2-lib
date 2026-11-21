# The `ppk2` command

`ppk2` does from a terminal what the Power Profiler app does with a
PPK2: find it, switch power to the DUT, and record current and digital
inputs to a file. `python -m ppk2` is the same program, and every
command has `--help`.

Only one program can hold a PPK2. Quit the app before you start.

| Command | What it does |
|---|---|
| [`ppk2 list`](#ppk2-list) | Shows the PPK2s attached and the state of their ports |
| [`ppk2 discover`](#ppk2-discover) | Prints the path of the data port |
| [`ppk2 metadata`](#ppk2-metadata) | Prints the calibration |
| [`ppk2 capture`](#ppk2-capture) | Records to a CSV or a `.ppk2` file |
| [`ppk2 convert`](#ppk2-convert) | Turns a CSV into a `.ppk2` file |
| [`ppk2 power`](#ppk2-power) | Switches power to the DUT |
| [`ppk2 run`](#ppk2-run) | Runs a command with the DUT powered |
| `ppk2 version` | Prints the version |

## Options shared by several commands

| Option | Default | Accepted by | Meaning |
|---|---|---|---|
| `--serial TEXT` | none | `discover`, `metadata`, `power`, `capture`, `run` | The USB serial number of one PPK2. Needed when several are attached |
| `--port PATH` | none | `discover`, `metadata`, `power`, `capture`, `run` | The path of the data port. Skips the search |
| `--vdd FLOAT` | 3.3 | `power`, `capture`, `run` | The DUT's supply voltage in volts, kept between 0.8 and 5.0 |
| `--source` | off | `power`, `capture`, `run` | Source meter mode instead of Ampere meter mode |

`--vdd` means two things. In Source meter mode it is the voltage the
PPK2 supplies. In Ampere meter mode it sets nothing, but the
calibration uses it: give the voltage the DUT really runs at.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Done |
| 1 | A device or session error, with a one-line message. Also a capture without a single sample |
| 2 | Wrong usage |
| 130 | Stopped by Ctrl-C |

`ppk2 run` returns the exit code of its command instead: 127 if the
command was not found, 128 plus the signal number if a signal killed
it.

Errors never show a traceback. They are one line starting with
`error:`, and [troubleshooting](troubleshooting.md) lists
them.

## `ppk2 list`

```console
$ ppk2 list
PPK2  serial=A1B2C3D4E5F6
  /dev/cu.usbmodemA1B2C3D4E5F62   [data port]
  /dev/cu.usbmodemA1B2C3D4E5F64   [idle]
```

One block per PPK2. `[data port]` is the port that answers, `[idle]`
the other one. `[busy: held by another process?]` means the port could
not be opened: close the program that holds it.

The exit code is 0 when every PPK2 has its data port identified, and 1
otherwise. With no PPK2 attached it prints `no PPK2 found`. When a data
port could not be identified it says so under that PPK2.

## `ppk2 discover`

```console
$ ppk2 discover
/dev/cu.usbmodemA1B2C3D4E5F62
```

Prints the path of the data port, for use in a script. It fails when no
PPK2 is attached, and when several are and `--serial` is missing.

## `ppk2 metadata`

```console
$ ppk2 metadata
Calibrated: false
HW:         46575
IA:         60
VDD:        3300 mV
mode:       2 (Source meter)
R : [    1.002119e+03,     1.014783e+02,     1.033613e+01,     9.682840e-01,     5.643343e-02]
GS: [    1.000000e-19,     1.258190e+02,     1.955098e+01,     2.673501e+00,     7.893860e-02]
GI: [    1.000000e+00,     9.650117e-01,     9.590379e-01,     9.480509e-01,     9.562991e-01]
O : [    1.229457e+02,     8.335670e+01,     7.085423e+01,     5.442371e+01,     9.623315e+01]
S : [   -7.046158e-09,     5.256595e-08,     4.921795e-07,     9.235569e-06,     2.415189e-03]
I : [    5.155071e-08,    -2.181893e-07,     5.512471e-05,    -2.677141e-04,    -8.630627e-03]
UG: [    1.000000e+00,     1.000000e+00,     1.000000e+00,     1.000000e+00,     1.000000e+00]
```

The calibration the PPK2 reports, five values per line, one per
measurement range. `VDD` and `mode` are the supply voltage and the mode
the PPK2 was left in. The
[measurement principle](../measure/principle.md#from-a-reading-to-a-current)
says what each line is, and why `Calibrated: false` is not a fault.

## `ppk2 capture`

```console
$ ppk2 capture --out first.csv --seconds 5 --source --vdd 3.3
opening session (Source meter mode, vdd=3300 mV)
capturing 5.00 s -> first.csv (Ctrl-C to stop early)
  [  1.0s]       99504 samples  mean  946.81 µA
  [  2.0s]      199681 samples  mean  821.63 µA
  [  3.0s]      300033 samples  mean  778.87 µA
  [  4.0s]      400385 samples  mean  757.42 µA
captured 500736 samples over 5.01 s (100035 Hz)
```

| Option | Default | Meaning |
|---|---|---|
| `--out`, `-o PATH` | required | The file to write. A name ending in `.ppk2`, in any letter case, gives a session file, any other name a CSV |
| `--seconds`, `-s FLOAT` | 30 | How long to capture |
| `--user-gain RANGE:GAIN` | none | A gain for one range, 0 to 4. Can be repeated. See [gains](architecture.md#gains) |

What to know about a capture:

- It switches the DUT on as it starts and off as it ends, in both
  modes, so the boot is in the file. The current rises about 10 ms
  into it.
- Progress goes to the terminal once per second, the samples go to the
  file only.
- Currents below 0.2 µA are written as 0, as the app does.
- Ctrl-C stops early, completes the file and exits with 130.
- If samples were lost, the summary says how many. It also warns when
  the rate over the capture fell below 95,000 samples per second.

[File formats](../measure/formats.md) describes both kinds of file.

## `ppk2 convert`

```console
$ ppk2 convert first.csv first.ppk2
wrote first.ppk2: 500736 samples at 100000 S/s (5.01 s)
```

Turns a CSV capture, plain or gzipped, into a `.ppk2` session file. It
needs the `Timestamp(ms)` and `Current(uA)` columns and reads the
digital inputs from `D0-D7` if the column is there. The sample rate
comes from the timestamps and must be a power of ten up to 100,000.

A gap in the timestamps is kept as lost samples. A gap of more than
one second is refused, and so are timestamps that go back. If the
conversion fails, an earlier file of the same name is left as it was.

## `ppk2 power`

```sh
ppk2 power on --hold --source --vdd 3.3    # keep the DUT powered until Ctrl-C
ppk2 power off
```

Switches power to the DUT, as the app's Enable power output does.

Power lasts only while the command runs, because the PPK2 cuts it when
its serial port closes. `ppk2 power on` without `--hold` therefore
powers the DUT for about a second and is of little use. With `--hold`
it waits for Ctrl-C.

## `ppk2 run`

```sh
ppk2 run --source --vdd 3.0 -- west flash
ppk2 run --source --vdd 3.0 --out flash.csv -- west flash
```

Runs the command after `--` with the DUT powered, and returns its exit
code. With `--out` it records while the command runs, to a CSV or a
`.ppk2` file. It reads the stream in a second thread for that time,
with or without `--out`, since the PPK2 cannot be told to pause.

Ctrl-C is passed on to the command. However the command ends, the DUT
is unpowered afterwards. [Flashing](recipes.md#flash-a-dut-powered-by-the-ppk2) is
the usual reason to use it.

## Signals

Ctrl-C, `kill` and a closed terminal all end a command the same way:
the stream is stopped, the DUT is switched off, the port is closed and
the output file is completed. The exit code is 130 after Ctrl-C, and
128 plus the signal number after `kill` or a closed terminal.

If the process is killed outright, with `kill -9`, the PPK2 still cuts
power by itself, but it keeps streaming. The next `ppk2` command stops
that stream when it opens the PPK2.

## See also

- [Getting started](getting-started.md)
- [Troubleshooting](troubleshooting.md)
