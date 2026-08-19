# ppk2-lib

> **Experimental release.** The API is functional and
> bench-validated but not yet frozen — expect breaking changes
> between 0.x versions. Feedback and issues welcome.

Python library + CLI for Nordic Semiconductor's **Power Profiler
Kit II (PPK2)** — capture calibrated current traces and digital
logic channels at 100 kSPS, from scripts, from the terminal, or
from CI.

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

## Why this exists

- **GUI-parity output.** CSV captures are byte-format-identical
  to the Nordic Power Profiler GUI's export — same 11 columns,
  same calibration math, same spike filter, same noise-floor
  clamp. A capture from this tool and one from the GUI diff
  cleanly.
- **Scriptable end-to-end.** Discovery, session lifecycle, DUT
  power (source and ammeter modes), capture, and per-sample
  callbacks are all plain sync Python. `ppk2 run -- <cmd>`
  powers your DUT, runs a command (flash, benchmark, test),
  and optionally captures the whole thing.
- **Verified against the wire.** The protocol layer is a
  clean-room implementation cross-validated on live hardware
  against the Nordic Power Profiler GUI: Kolmogorov–Smirnov
  statistics below 0.005
  between stacks on 60 s captures — see the committed
  comparison round in `validation/evidence/noise_floor_gui/`.
- **Typed and tested.** pyright strict (one scoped, documented
  suppression), ruff, 154 fast tests + 8 hardware-in-the-loop
  tests, reference DUT firmware included for reproducing the
  HIL bench.

## Quick start

```sh
# 1. Plug in a PPK2 (USB), then:
ppk2 list                 # every connected PPK2 + port status
ppk2 metadata             # per-device calibration block

# 2. Ammeter mode (PPK2 in series with your DUT's supply):
ppk2 capture --out idle.csv --seconds 30

# 3. Source mode (PPK2 powers the DUT at 3.0 V):
ppk2 capture --out boot.csv --seconds 10 --source --vdd 3.0

# 4. Power the DUT and run a command against it:
ppk2 run --source --vdd 3.0 -- west flash
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
`firmware/bench-dut/` contains reference Zephyr firmware
(pre-built hex for the nRF52840 DK, nRF54L15 DK, and nRF54LM20
DK) that toggles D0 at 5 Hz and D1 at 0.5 Hz — a deterministic
signal the hardware tests assert against. See its README for
wiring.

`validation/` holds a port-agnostic A/B harness — capture the
same bench with any two ppk2-compatible binaries (or a GUI CSV
export) and diff the results statistically — plus, under
`validation/evidence/`, the committed comparison rounds (reports,
gzipped reference captures, parity plots) behind this README's
GUI-parity claims.

Layout rule of thumb: `firmware/` holds the Zephyr apps —
`bench-dut/` is test infrastructure (the reference DUT the HIL
tier asserts against), `trace-demo/` is a worked example you
copy from.

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
- `firmware/bench-dut/README.md` — the reference DUT: wiring,
  per-board pins, build/flash recipes.
- `validation/README.md` — the A/B capture-comparison harness.

A full documentation site (mkdocs) is planned; these files are
its seed chapters.

## License

Apache-2.0 OR MIT, at your option.
