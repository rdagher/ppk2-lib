# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.1.0 (not yet released)

First public release. Experimental: the API may change between 0.x
versions.

### Command line

- `ppk2 list`, `discover` and `metadata` find a PPK2 and show its
  calibration. `ppk2 list --mask-serial` hides all but the last four
  characters of each serial number, for a screenshot or a recording.
- `ppk2 capture` records current and digital inputs in Ampere meter or
  Source meter mode, to the 11-column CSV that Nordic's Power Profiler
  app exports, or to a session file in the app's `.ppk2` format.
  `--seconds N` gives N seconds of samples, 500,000 for 5 s, and the
  command exits 1 if they do not all arrive.
- `ppk2 convert` turns a CSV capture into a `.ppk2` file.
- `ppk2 power on|off` switches power to the device under test (DUT),
  and `--hold` keeps it on until Ctrl-C.
- `ppk2 run -- <command>` powers the DUT for the duration of a command
  and can record meanwhile. When it is terminated, it terminates the
  command.
- Exit codes: 1 for an error with the PPK2, the session or the output
  file, with one line starting with `error:`. 2 for a usage error, and
  130 after Ctrl-C. `run` returns the command's code.

### Library

- `ppk2.protocol`: commands, calibration text, sample decoding,
  calibration formula and stream parser. This layer uses the standard
  library only.
- `ppk2.client`: discovery of the data port, and a `Session` with
  Ampere meter and Source meter modes, power switching, user gain, a
  voltage limit and spike-filter settings.
- Lost samples are reported and keep their place in the trace. The
  files record each as 0.2 µA, as Nordic's app does.
- `Session.capture` calls a function for every sample until it returns
  `False`. `keep_going` ends a capture on a PPK2 that sends nothing.
- When bytes of the stream are lost, the parser finds the start of the
  words again and goes on.
- A session leaves the PPK2 quiet for the next program, and opens a
  PPK2 that another program left streaming.

### Validation

- The parser gives the same samples as the app's on a recorded stream
  that crosses all five measurement ranges.
- Captures of the same bench by the app and by `ppk2 capture` agree:
  the mean current and the mean charge of the marked regions within
  0.11 %, in both modes, and the same 0.2 µA floor. See
  [`validation/evidence/`](validation/evidence/bench_dut/README.md).
- Hardware tests and their bench firmware are in
  [`tests/hil/`](tests/hil/README.md).

### Limitations

- Synchronous only.
- On a bench it has run on macOS only. Linux and Windows pass the unit
  tests. On Windows, `power on --hold` and Ctrl-C during `run` do not
  work yet.
- Captures are continuous, like the Data logger mode of the app. There
  is no equivalent of its Scope mode, which samples on a trigger.
- A capture starts about 10 ms before the DUT's power comes up. See
  the [protocol page](docs/measure/protocol.md#10-known-caveats) for
  the measurements.
- `.ppk2` files follow the layout the app documents. One 30 s file
  was opened in the app and showed the figures of its CSV.
