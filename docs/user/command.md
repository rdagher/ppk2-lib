# Command reference

`ppk2` does from a terminal what the [Power Profiler app](https://docs.nordicsemi.com/r/bundle/nrf-connect-for-desktop/page/app/pc-nrfconnect-ppk/using_ppk_app.html) does
with a PPK2: find it, switch power to the device under test (DUT), and
record current and digital inputs to a file. `python -m ppk2` is the
same program, and every command has `--help`.

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

## Common options

| Option | Default | Accepted by | Meaning |
|---|---|---|---|
| `--serial TEXT` | none | `discover`, `metadata`, `power`, `capture`, `run` | The USB serial number of one PPK2. Needed when several are attached |
| `--port PATH` | none | `discover`, `metadata`, `power`, `capture`, `run` | The path of the data port. Skips the search |
| `--vdd FLOAT` | 3.3 | `power`, `capture`, `run` | The DUT's supply voltage in volts. A value outside 0.8 to 5.0 is brought back to the nearest of the two |
| `--source` | off | `power`, `capture`, `run` | Source meter mode instead of Ampere meter mode |

`--vdd` means two things:

- In Source meter mode, it is the voltage the PPK2 supplies.
- In Ampere meter mode, it sets nothing, but the calibration uses it:
  give the voltage the DUT really runs at.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Done |
| 1 | An error with the PPK2, the session or the output file, with a one-line message. Also a capture that ends with fewer samples than `--seconds` asks for |
| 2 | Wrong usage |
| 130 | Stopped by Ctrl-C |

`ppk2 run` returns the exit code of its command instead:

- 127 if the command was not found;
- 128 plus the signal number if a signal killed it.

An error is one line starting with `error:`. See
[troubleshooting](troubleshooting.md) for the list. A wrong option or
value is reported with the usage line of the command.

## `ppk2 list`

```console
$ ppk2 list
PPK2  serial=A1B2C3D4E5F6
  /dev/cu.usbmodemA1B2C3D4E5F62   [data port]
  /dev/cu.usbmodemA1B2C3D4E5F64   [idle]
```

One block per PPK2, with a mark on each port:

- `[data port]`: the port that answers;
- `[idle]`: the other one;
- `[busy: held by another process?]`: the port could not be opened.
  Close the program that holds it.

`--mask-serial` prints only the last four characters of each serial
number, in the port paths too. It is meant for a screenshot or a
recording; the masked paths are not usable as `--port`.

The exit code is 0 when every PPK2 has its data port identified, and 1
otherwise. If no PPK2 is attached, it prints `no PPK2 found`. If a
data port could not be identified, it says so under that PPK2.

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

It prints the calibration the PPK2 reports, five values per line, one
per measurement range. `VDD` and `mode` are the supply voltage and the
mode the PPK2 was left in. See the
[Principle](../measure/principle.md#calibration) page
for what each line is, and why `Calibrated: false` is not a fault.

## `ppk2 capture`

```console
$ ppk2 capture --out first.csv --seconds 5 --source --vdd 3.3
opening session (Source meter mode, vdd=3300 mV)
capturing 5.00 s -> first.csv (Ctrl-C to stop early)
  [  1.0s]      100249 samples  mean  945.69 µA
  [  2.0s]      199681 samples  mean  826.16 µA
  [  3.0s]      300033 samples  mean  783.65 µA
  [  4.0s]      400385 samples  mean  761.46 µA
captured 500000 samples over 5.00 s (99936 Hz)
```

| Option | Default | Meaning |
|---|---|---|
| `--out`, `-o PATH` | required | The file to write. A name ending in `.ppk2`, in any letter case, gives a session file, any other name a CSV |
| `--seconds`, `-s FLOAT` | 30 | How long to capture, as seconds of samples |
| `--user-gain RANGE:GAIN` | none | A gain from 0.9 to 1.1 for one range, 0 to 4. Can be repeated. See [gains](../develop/architecture.md#gains) |

What to know about a capture:

- It switches the DUT on as it starts and off as it ends, in both
  modes, so the boot is in the file. The current rises about 10 ms
  into it. This is a choice: every capture starts from a DUT that is
  off. In Source meter mode the PPK2 is the supply, and in Ampere meter
  mode it sits in series with it, so in both the switch is in the DUT's
  power path.
- It ends when the file holds the seconds asked for: 500,000 samples
  for 5 s. If they have not all come one second after that time, it
  stops, keeps the file and exits with 1.
- Progress goes to the terminal once per second, the samples go to the
  file only.
- Currents below 0.2 µA are written as 0, as the app does.
- Ctrl-C stops early, completes the file and exits with 130.
- If samples were lost, the summary says how many. It also warns when
  the rate over the capture fell below 95,000 samples per second.

See [File formats](../measure/formats.md) for both kinds of file.

## `ppk2 convert`

```console
$ ppk2 convert first.csv first.ppk2
wrote first.ppk2: 500000 samples at 100000 S/s (5.00 s)
```

Turns a CSV capture, plain or gzipped, into a `.ppk2` session file.
The CSV needs:

- the `Timestamp(ms)` and `Current(uA)` columns. The digital inputs
  are read from `D0-D7` if the column is there.
- a sample rate, taken from the timestamps, that is a power of ten up
  to 100,000.
- digital inputs that are `0` or `1`. The `-` and `X` that the app
  writes when it exports at a lower rate are not accepted.

A gap in the timestamps is filled with samples of 0.2 µA, the way a
[lost sample](../measure/formats.md#lost-samples) is recorded. A gap of
more than one second is refused, and so are timestamps that go back. If the
conversion fails, an earlier file of the same name is left as it was.

## `ppk2 power`

```sh
ppk2 power on --hold --source --vdd 3.3    # keep the DUT powered until Ctrl-C
ppk2 power off
```

Switches power to the DUT, as the app's Enable power output does.

Power lasts only while the command runs, because the PPK2 cuts it when
its serial port closes. So `ppk2 power on` without `--hold` powers the
DUT for an instant only, which is of little use. With `--hold` it waits
for Ctrl-C. `--hold` is not supported on Windows yet.

## `ppk2 run`

```sh
ppk2 run --source --vdd 3.3 -- west flash
ppk2 run --source --vdd 3.3 --out flash.csv -- west flash
```

Runs the command after `--` with the DUT powered, and returns its exit
code. With `--out` it records while the command runs, to a CSV or a
`.ppk2` file. It reads the stream in a second thread for that time,
with or without `--out`, since the PPK2 cannot be told to pause.

Ctrl-C is passed on to the command. When `ppk2 run` itself is
terminated, by `kill` or a closed terminal, it terminates the command
first, and kills it if it has not ended after 5 s. However the command
ends, the DUT is unpowered afterwards. The usual reason to use it is
[flashing](recipes.md#flashing-a-dut-powered-by-the-ppk2).

## Signals

Ctrl-C, `kill` and a closed terminal all end a command the same way:

- the stream is stopped;
- the DUT is switched off;
- the port is closed;
- the output file is completed.

The exit code is 130 after Ctrl-C, and 128 plus the signal number after
`kill` or a closed terminal. `ppk2 power on --hold` is the exception:
Ctrl-C is how it is meant to end, and it returns 0.

If the process is killed outright, with `kill -9`, the PPK2 still cuts
power by itself, but it keeps streaming. The next `ppk2` command stops
that stream when it opens the PPK2.

## See also

- [Getting started](getting-started.md)
- [Troubleshooting](troubleshooting.md)
