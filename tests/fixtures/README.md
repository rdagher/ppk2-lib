# Test fixtures

Bytes recorded from a PPK2, and what they should parse to. With these
the unit tests need no hardware.

| File | What it is |
|---|---|
| [`metadata.raw`](metadata.raw) | The calibration text a PPK2 sent, 1,032 bytes (2026-06-05). |
| [`metadata.parsed.json`](metadata.parsed.json) | Those values as read by Nordic's own code. |
| [`stream_poweron.bin`](stream_poweron.bin) | 600 samples (6 ms) of the same PPK2's stream while it powers a dev kit on. All five measurement ranges, nine range changes. |
| [`parsed_poweron.csv`](parsed_poweron.csv) | Those samples as parsed by Nordic's own code: current and logic byte. |

The stream was recorded on 2026-11-20 in Source meter mode at 3.3 V,
with the [bench firmware](../hil/bench-dut/) on an nRF54LM20 DK.

## Origin of the expected values

`parsed_poweron.csv` is what the parser of Nordic's Power Profiler app
gives for `stream_poweron.bin`, with `metadata.raw` as calibration
(`pc-nrfconnect-ppk` v4.4.1, `src/device/serialDevice.ts`). To produce
it again, you need Node 24 or newer and a checkout of the app at that
tag:

```sh
git clone --branch v4.4.1 --depth 1 https://github.com/nordicsemi/pc-nrfconnect-ppk
node tests/fixtures/make_reference.mjs pc-nrfconnect-ppk
```

Run this way, the script writes the two reference files again, byte for
byte.

The app's source is not copied here: its licence allows using it, not
redistributing it. [`nordic_hooks.mjs`](nordic_hooks.mjs) replaces the
two parts that tie the parser to the desktop app: the serial worker and
the logger.

`metadata.parsed.json` is what the same code reads from `metadata.raw`.
The script writes both files.

## Coverage

The fixtures cover:

- bit extraction;
- the calibration of each range;
- the spike filter across range changes;
- the logic byte.

They hold no lost sample and no corrupt word: those cases are unit
tests in [`tests/protocol/test_stream.py`](../protocol/test_stream.py).
