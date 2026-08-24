# ppk2-lib

> **Experimental release.** The API is functional and
> bench-validated but not yet frozen — expect breaking changes
> between 0.x versions. Feedback and issues welcome.

Python library + CLI for Nordic Semiconductor's **Power Profiler
Kit II (PPK2)** — calibrated current traces and eight digital logic
channels at 100 kSPS, from scripts, from the terminal, or from CI.

One install, both surfaces:

```sh
pip install "git+https://github.com/rdagher/ppk2-lib"
```

```sh
ppk2 capture --out trace.csv --seconds 30     # CLI
```

```python
from ppk2 import Session, Mode, find_ppk2      # library

with Session.open(find_ppk2().device) as s:
    s.set_mode(Mode.AMPERE)
    s.start_measuring()
    s.power_on()
    s.capture(lambda sample: sample.current_micro_amps < 1000)
```

## Why trust the numbers

- **Clean-room protocol implementation**, cross-validated on live
  hardware against Nordic's own Power Profiler GUI — committed
  evidence rounds below.
- **GUI-parity output** — CSV captures are byte-format-identical to
  the GUI's export: same columns, calibration math, spike filter, and
  noise-floor clamp. A capture from this tool and one from the GUI
  diff cleanly.
- **Typed and tested** — pyright strict, ruff, 150+ fast tests and a
  hardware-in-the-loop tier, with the reference DUT firmware in-repo
  ([`firmware/bench-dut/`](firmware/bench-dut/)).

| Round | Bench | Headline result |
|---|---|---|
| [Noise floor](validation/evidence/noise_floor_gui/) | ammeter, open leads (sub-µA) | headers byte-identical, KS 0.0002 |
| [Trace-demo workloads](validation/evidence/trace_demo/README.md) | nRF52840 DK source 3.0 V + nRF54LM20DK ammeter 3.3 V | per-region energy within 0.31 %, workload-region KS ≤ 0.014 |

![GUI-vs-CLI parity on the nRF54LM20 DK: sync-aligned trace overlay and per-region ECDFs](validation/evidence/trace_demo/plots/nrf54lm20_ammeter_parity.png)

The harness behind these rounds ships in the repo
([`validation/README.md`](validation/README.md)): capture the same
bench with any two ppk2-compatible binaries — or a GUI CSV export —
and diff them statistically.

## Quick start

```sh
# 1. Plug in a PPK2 (USB), then:
ppk2 list                 # every connected PPK2 + port status
ppk2 metadata             # per-device calibration block

# 2. Ammeter mode (PPK2 in series with your DUT's supply):
ppk2 capture --out idle.csv --seconds 30

# 3. Source mode (PPK2 powers the DUT at 3.0 V):
ppk2 capture --out boot.csv --seconds 10 --source --vdd 3.0

# 4. Hold DUT power until Ctrl-C (a bench supply while you flash/debug):
ppk2 power on --hold --source --vdd 3.0

# 5. Run a command with the DUT powered — capture is optional (--out):
ppk2 run --source --vdd 3.0 -- west flash
ppk2 run --source --vdd 3.0 --out run.csv -- pytest -m hardware
```

The CSV format is the Nordic GUI's 11-column export:
`Timestamp(ms),Current(uA),D0-D7,D0..D7` — logic channels
decoded per sample, D0 leftmost in the bit string.

## Library layers

| Layer | Import | Depends on |
|---|---|---|
| `ppk2.protocol` | opcodes, metadata parser, sample decoder, calibration formula, stream parser | stdlib only |
| `ppk2.client` | discovery (`find_ppk2`, `list_ppk2s`) + `Session` state machine | pyserial |
| `ppk2.cli` | the `ppk2` binary (typer) | both |

Everything public re-exports from the top-level `ppk2` package.
The protocol layer being stdlib-only means you can re-decode a
saved byte stream (or build your own transport) without pulling
in serial-port machinery.

## Development

Tooling: [uv](https://docs.astral.sh/uv/) +
[just](https://github.com/casey/just).

```sh
just sync        # install all deps into .venv
just ci          # pyright strict + ruff + fast test tier
just test-hw     # HIL tier — needs a PPK2 + the bench DUT
just build       # wheel + sdist into dist/
```

The HIL bench is reproducible from this repo alone:
[`firmware/bench-dut/`](firmware/bench-dut/) contains reference
Zephyr firmware for the nRF52840, nRF54L15, and nRF54LM20 DKs
(hexes built locally with `just hex`, or by the CI firmware
matrix) that toggles D0 at 5 Hz and D1 at 0.5 Hz — a
deterministic signal the hardware tests assert against. See its
[README](firmware/bench-dut/README.md) for wiring.

[`validation/`](validation/) holds the A/B comparison harness and,
under [`validation/evidence/`](validation/evidence/), the committed
GUI-parity rounds shown above.

## Status

Experimental (`0.1.0`). Works on macOS and Linux; Windows is
CI-tested at the fast tier but not yet bench-validated. Not
published to PyPI yet — install from git.

Upstream references (protocol semantics are cited, never
vendored): Nordic's
[pc-nrfconnect-ppk](https://github.com/NordicSemiconductor/pc-nrfconnect-ppk)
GUI and IRNAS's
[ppk2-api-python](https://github.com/IRNAS/ppk2-api-python).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — the three layers, the
  session lifecycle (with sequence diagram), the threading model.
- [Protocol notes](docs/PROTOCOL.md) — opcodes, metadata format,
  sample frame, stream reassembly, calibration formula, CSV
  format, known firmware caveats.
- [`firmware/bench-dut/README.md`](firmware/bench-dut/README.md) — the reference DUT: wiring,
  per-board pins, build/flash recipes.
- [`validation/README.md`](validation/README.md) — the A/B capture-comparison harness.

## License

Apache-2.0 OR MIT, at your option.
