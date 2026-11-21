# Changelog

## 0.1.0

First public release. Experimental: the API may change between 0.x
versions.

### Command line

- `ppk2 list`, `discover` and `metadata` find a PPK2 and show its
  calibration.
- `ppk2 capture` records current and digital inputs in Ampere meter or
  Source meter mode, to the 11-column CSV that Nordic's Power Profiler
  app exports, or to a session file in the app's `.ppk2` format.
- `ppk2 convert` turns a CSV capture into a `.ppk2` file.
- `ppk2 power on|off` switches power to the device under test (DUT),
  and `--hold` keeps it on until Ctrl-C.
- `ppk2 run -- <command>` powers the DUT for the duration of a command
  and can record meanwhile.
- Exit codes: 1 for a device or session error with a one-line message,
  2 for a usage error, 130 after Ctrl-C. `run` returns the command's
  code.

### Library

- `ppk2.protocol`: commands, calibration text, sample decoding,
  calibration formula and stream parser, on the standard library
  alone.
- `ppk2.client`: discovery of the data port, and a `Session` with
  Ampere meter and Source meter modes, power switching, user gain, a
  voltage limit and spike-filter settings.
- Lost samples are reported and keep their place in the trace. The
  files record each as 0.2 µA, as Nordic's app does.
- A session leaves the PPK2 quiet for the next program, and opens a
  PPK2 that another program left streaming.

### Checked against Nordic's app

- The parser gives the same samples as the app's on a recorded stream
  that crosses all five measurement ranges.
- Captures of the same bench by the app and by `ppk2 capture` agree:
  charge per marked region within 0.31 %, and the same distribution at
  the noise floor. See [`validation/evidence/`](validation/evidence/).
- Hardware tests and their bench firmware are in
  [`tests/hil/`](tests/hil/README.md).

### Limits

- Synchronous only.
- Windows runs the unit tests but has not been tried on a bench, and
  `power on --hold` and Ctrl-C handling in `run` use POSIX calls.
- Only the sampling mode of the PPK2 is covered, not its trigger mode.
- A capture starts about 10 ms before the DUT's power comes up. The
  [protocol page](docs/measure/protocol.md#10-known-caveats) has
  the measurements.
- `.ppk2` files follow the layout the app documents. Loading one in the
  app itself is still to be confirmed.
