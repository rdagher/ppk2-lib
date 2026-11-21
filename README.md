# ppk2-lib

A Python library and command-line tool for Nordic's Power Profiler
Kit II (PPK2). It records current and the eight digital inputs at
100,000 samples per second from a script, a terminal or a CI job,
without the Power Profiler app.

This is an experimental release (0.1.0). It works and is checked on
hardware, but the API may still change between 0.x versions.

## Install

```sh
pip install "git+https://github.com/rdagher/ppk2-lib"
```

You need Python 3.11 or newer. The unit tests run on Linux, macOS and
Windows with Python 3.11 and 3.13. The hardware tests have only run on
macOS 26, so Windows and Linux are untested on a bench. On Windows,
`ppk2 power on --hold` and Ctrl-C handling in `ppk2 run` use POSIX
calls that Windows does not have.

## A first capture

Wire the PPK2 as you would for the app, quit the app, and run:

```console
$ ppk2 list
PPK2  serial=A1B2C3D4E5F6
  /dev/cu.usbmodemA1B2C3D4E5F62   [data port]
  /dev/cu.usbmodemA1B2C3D4E5F64   [idle]

$ ppk2 capture --out boot.csv --seconds 3 --source --vdd 3.3
opening session (Source meter mode, vdd=3300 mV)
capturing 3.00 s -> boot.csv (Ctrl-C to stop early)
  [  1.0s]      100191 samples  mean  947.46 µA
  [  2.0s]      199681 samples  mean  823.90 µA
  [  3.0s]      300033 samples  mean  781.88 µA
captured 301056 samples over 3.01 s (100099 Hz)
```

This is Source meter mode: the PPK2 powers the device under test (DUT)
at 3.3 V. `boot.csv` has the same 11 columns as the app's export, and
the DUT's boot is at the start of it. Without `--source` the PPK2 is in
Ampere meter mode and measures a DUT that has its own supply.

The DUT is switched on as the capture starts: the current rises about
10 ms into the file.

A few more commands:

```sh
ppk2 capture --out idle.ppk2 --seconds 30    # a session file in the app's format
ppk2 convert boot.csv boot.ppk2              # the same, from a CSV
ppk2 power on --hold --source --vdd 3.3      # keep the DUT powered until Ctrl-C
ppk2 run --source --vdd 3.3 -- west flash    # power the DUT for one command
```

And from Python:

```python
from ppk2 import Mode, Session, find_ppk2

with Session.open(find_ppk2().device) as session:
    session.set_mode(Mode.AMPERE)
    session.start_measuring()
    session.power_on()
    session.capture(lambda sample: sample.current_micro_amps < 1000)
```

`capture` calls your function for every sample and stops when it
returns `False`.

## Documentation

The documentation is in [`docs/`](docs/index.md) and builds into a site
with `just docs`. It has three parts.

| Part | Pages |
|---|---|
| Using it | [Getting started](docs/use/getting-started.md), [the `ppk2` command](docs/use/command.md), [recipes](docs/use/recipes.md), [architecture](docs/use/architecture.md), [API reference](docs/use/api.md), [troubleshooting](docs/use/troubleshooting.md) |
| How it measures | [Measurement principle](docs/measure/principle.md), [protocol](docs/measure/protocol.md), [file formats](docs/measure/formats.md) |
| Validation against Nordic's app | [Method](docs/validation/method.md), [results](docs/validation/results.md) |

The package has three layers, each usable alone: `ppk2.protocol` for
the bytes, `ppk2.client` for the device, `ppk2.cli` for the command.
The [changelog](CHANGELOG.md) lists what 0.1.0 contains and its limits.

## How the numbers are checked, in short

The parser gives the same samples as the parser of Nordic's app on a
recorded stream that crosses all five measurement ranges. Captures of
the same bench by the app and by `ppk2 capture` agree within 0.31 % on
the energy of each marked region.

![The app's capture and this tool's, overlaid, on the nRF54LM20 DK](validation/evidence/trace_demo/plots/nrf54lm20_ampere_parity.png)

All of this was measured on one PPK2. The reference is Nordic's app,
not a calibrated instrument.

## Development

```sh
just sync        # install into .venv (needs uv and just)
just ci          # type check, lint, unit tests
just test-hw     # hardware tests: needs a PPK2 and the bench firmware
just docs        # build the documentation site into site/
```

## Origin and licence

The protocol code was written from a reading of the source of Nordic's
app ([pc-nrfconnect-ppk](https://github.com/nordicsemi/pc-nrfconnect-ppk))
and from measurements on a bench. It contains none of that source,
whose licence allows reading and running it but not redistributing it.
The same goes for IRNAS's
[ppk2-api-python](https://github.com/IRNAS/ppk2-api-python), which is
GPL-2.0.

Nordic also has a PPK2 script of its own, the `ppk2` skill of Nordic
MCP: a local server that lets an AI assistant drive the kit and watch a
live trace. It is a separate program with a different aim.

ppk2-lib is not affiliated with or endorsed by Nordic Semiconductor.
PPK2, Power Profiler Kit and nRF are Nordic's product names.

Licensed under Apache-2.0 or MIT, at your option.
