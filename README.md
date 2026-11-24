# ppk2-lib

ppk2-lib provides a Python library and CLI for scripted measurements
with Nordic's
[Power Profiler Kit II](https://www.nordicsemi.com/Products/Development-hardware/Power-Profiler-Kit-2)
(PPK2). It records current and the eight digital inputs at 100,000
samples per second, from a terminal or in CI. Its captures
are checked against Nordic's
[Power Profiler app](https://docs.nordicsemi.com/r/bundle/nrf-connect-for-desktop/page/app/pc-nrfconnect-ppk/using_ppk_app.html).

A GPIO that the firmware raises around a piece of code shows on a
digital input, so a capture also tells
[what that code draws](docs/user/recipes.md#current-of-a-marked-region).

This is an experimental release (0.1.0). It works and is checked on
hardware, but the API may still change between 0.x versions.

![From a terminal: the PPK2 found, three seconds recorded to a CSV file, then converted to a file for the app](docs/img/quickstart.gif)

## Installation

```sh
pip install ppk2-lib
```

Or with [uv](https://docs.astral.sh/uv/):

```sh
uv tool install ppk2-lib
uvx --from ppk2-lib ppk2 list
```

You need Python 3.11 or newer. On Windows, two things do not work yet:
see [platform notes](docs/user/getting-started.md#windows).

## Quick start

Wire the PPK2 as for the app, quit the app, and run:

```console
$ ppk2 list
PPK2  serial=A1B2C3D4E5F6
  /dev/cu.usbmodemA1B2C3D4E5F62   [data port]
  /dev/cu.usbmodemA1B2C3D4E5F64   [idle]

$ ppk2 capture --out boot.csv --seconds 3 --source --vdd 3.3
opening session (Source meter mode, vdd=3300 mV)
capturing 3.00 s -> boot.csv (Ctrl-C to stop early)
  [  1.0s]       99329 samples  mean  954.17 µA
  [  2.0s]      199681 samples  mean  826.31 µA
captured 300000 samples over 3.00 s (100037 Hz)
```

With `--source`, the PPK2 powers the device under test (DUT) at 3.3 V.
Without it, the PPK2 is in Ampere meter mode, for a DUT with its own
supply.

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

## Documentation

The documentation is published at <https://rdagher.github.io/ppk2-lib/>,
built from [`docs/`](docs/index.md) by `just docs`.

![The parts. A developer, a CI job or an AI coding assistant run the ppk2 command or use the Python API on the host. The library drives the PPK2 over USB. The PPK2 measures the current of the DUT and samples its digital inputs. A capture is written as a CSV or a .ppk2 file. Beside them, one second of a capture with its marked regions](docs/img/architecture.png)

See the [changelog](CHANGELOG.md) for what 0.1.0 contains and for its
limits. For AI coding assistants, [`llms.txt`](llms.txt) maps the
documentation, and [`.claude/skills/ppk2/SKILL.md`](.claude/skills/ppk2/SKILL.md)
is a procedure for driving a PPK2.

## Validation

Captures of the same bench by the app and by `ppk2 capture` agree
within 0.11 % on the mean current and charge of the marked regions,
in both modes. See the [method](docs/validation/method.md) and
the [results](docs/validation/results.md), with their limits: one PPK2,
and the app as the reference.

## Development

```sh
just sync        # install into .venv (needs uv and just)
just ci          # type check, lint, unit tests
just test-hw     # hardware tests: needs a PPK2 and the bench firmware
just docs        # build the documentation site into site/
```

## Origin

The protocol code was written from a reading of the source of Nordic's
app ([pc-nrfconnect-ppk](https://github.com/nordicsemi/pc-nrfconnect-ppk))
and from bench measurements. It contains none of that source,
whose licence allows reading and running it but not redistributing it.

The code and the documentation were written with Claude Code and
reviewed by the author. The figures are checked on a bench against
Nordic's app: see the [method](docs/validation/method.md) and the
[results](docs/validation/results.md).

## Related projects

- Nordic's Power Profiler app: the reference for this package.
- The `ppk2` skill of Nordic MCP, Nordic's tooling for AI assistants.
- IRNAS's [ppk2-api-python](https://github.com/IRNAS/ppk2-api-python):
  another Python library for the PPK2, under GPL-2.0.

See [related projects](docs/index.md#related-projects) for more.

## Licence

[Apache-2.0](LICENSE-APACHE) or [MIT](LICENSE-MIT), at your option.

ppk2-lib is not affiliated with or endorsed by Nordic Semiconductor.
PPK2, Power Profiler Kit and nRF are Nordic's product names.
