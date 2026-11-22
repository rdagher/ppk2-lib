# Method

The claim this package makes is narrow: on the same PPK2 and the same
bench, it gives the numbers that Nordic's
[Power Profiler app](https://docs.nordicsemi.com/r/bundle/nrf-connect-for-desktop/page/app/pc-nrfconnect-ppk/using_ppk_app.html) gives. The app is the reference
throughout. This page describes how the claim is tested. See the
[results](results.md) page for what the tests found.

It is tested at three levels, from one sample to a whole bench:

| Level | What is compared | Against | Material |
|---|---|---|---|
| The parser | 600 recorded samples, one by one | The app's own parsing code | [`tests/fixtures/`](https://github.com/rdagher/ppk2-lib/tree/main/tests/fixtures) |
| Whole captures | Two captures of one bench, taken back to back | The app's CSV export | [`validation/`](https://github.com/rdagher/ppk2-lib/tree/main/validation) |
| A bench | What the tool reads from a signal known in advance | The bench firmware | [`tests/hil/`](https://github.com/rdagher/ppk2-lib/tree/main/tests/hil) |

## Parser comparison

The recording is `stream_poweron.bin`: 600 samples, 6 ms, taken while a
PPK2 in Source meter mode at 3.3 V powered up an nRF54LM20 DK. The
current climbs through all five measurement ranges and changes range
nine times. The calibration text of the same PPK2 is stored next to it.

The reference is `parsed_poweron.csv`: the output of the app's parser
for those bytes. It was produced by running the app's code outside the
app (`pc-nrfconnect-ppk` v4.4.1,
[`src/device/serialDevice.ts`](https://github.com/nordicsemi/pc-nrfconnect-ppk/blob/v4.4.1/src/device/serialDevice.ts)),
with a small Node script. To produce it again, run:

```sh
git clone --branch v4.4.1 --depth 1 https://github.com/nordicsemi/pc-nrfconnect-ppk
node tests/fixtures/make_reference.mjs pc-nrfconnect-ppk
```

The script needs Node 24 or newer, and writes the same two files, byte
for byte.

The app's source is not copied into this repository: its licence
allows using it, not redistributing it.

A unit test parses the same bytes with this package. It passes when:

- every current agrees to the three decimals the reference carries;
- every byte of digital inputs is identical.

This covers:

- the extraction of the fields;
- the calibration of each range;
- the spike filter across range changes.

It does not cover lost samples: the recording contains none. Those
cases are tested on streams built for the purpose, and there this
package differs from the app on purpose. See the
[results](results.md#differences-from-the-app) for the differences.

## Capture comparison

A round compares captures made by the app and by `ppk2 capture`, on a
bench that is not touched in between. They are taken within minutes of
each other, because a bench drifts: with the temperature, and with the
device under test (DUT) itself.

### Procedure

1. Set up the bench once: the DUT, its firmware, the wiring, the mode
   and the supply voltage. Note the position of every switch.
2. In the app: Start, then Enable power output. Stop after about 30 s.
   Save / Export to CSV at 100,000 samples per second.
3. Quit the app. Only one program can hold the PPK2.
4. Capture the same duration with `ppk2 capture`, in the same mode and
   at the same voltage.
5. Compare the files.

Better still, capture with `ppk2 capture` before the app as well as
after. The difference between those two captures is the drift of the
bench, and the app's capture lies between them.

Every capture contains the power-on, so the DUT boots in each.

Record with the round what a reader needs to repeat it:

- the version of the app;
- the firmware of the PPK2 and its calibration text (`ppk2 metadata`);
- the commit of this package.

### Compared quantities

[`validation/compare_cli.py`](https://github.com/rdagher/ppk2-lib/blob/main/validation/compare_cli.py)
reads the two files and reports:

- the header, which must be identical;
- the sample rate;
- the mean, standard deviation and maximum of the current;
- the Kolmogorov-Smirnov (KS) statistic between the two distributions;
- the duty cycle and edge rate of each digital input.

It passes when:

- the headers are identical;
- the means are within 1 %;
- the KS statistic is below 0.05.

For a firmware that marks its work with D0 and D1, a second script,
[`validation/regions.py`](https://github.com/rdagher/ppk2-lib/blob/main/validation/regions.py),
computes the current, the charge, the number and the width of the
marked regions in each file.

### Per-region comparison

The two captures are not the same seconds of the DUT's life, and three
things make whole-trace numbers differ for reasons that are not the
instrument:

- A capture that starts at power-on contains the boot, which varies
  from one power cycle to the next. The first seconds are left out.
- A firmware with two levels, a workload and an idle, is cut at a
  different point of its cycle in each capture. The two levels are then
  mixed in different proportions.
- A current drifts over minutes. Two captures of `ppk2 capture` four
  minutes apart differed by 0.05 % in the round of this release.

So a round is judged by kind of region. For the regions marked by one
digital input, two means are compared between the captures:

- the mean of their current;
- the mean of their charge, which is the current added up over a
  region's duration.

The regions are not paired one to one: the captures are different
seconds of the DUT's life and do not hold the same number of them.

The distribution of the current inside the workload and inside the
idle is compared as well. There is no energy in the comparison, because
a PPK2 measures current only.

## Hardware tests

The hardware tests do not compare with the app. They check the tool
against a signal that is known in advance, from the firmware in
[`tests/hil/bench-dut`](https://github.com/rdagher/ppk2-lib/tree/main/tests/hil/bench-dut).
D0 toggles at 5 Hz and D1 at 0.5 Hz. The CPU is busy while D0 is high,
so the current steps with D0.

Ten tests check that:

- the PPK2 is found and reports a usable calibration;
- samples arrive at 100,000 per second, within 10 %;
- D0 and D1 show the expected activity;
- a capture file has the app's format, and its digital columns agree
  with each other;
- nothing is left to read after a stream is stopped;
- the DUT is unpowered once a session has ended;
- two captures in a row both succeed;
- `ppk2 run` returns the exit code of its command.

To run them, in each mode:

```sh
just test-hw                          # Ampere meter mode
PPK2_HIL_SOURCE_MV=3300 just test-hw  # Source meter mode at 3.3 V
```

## Limitations

- Absolute accuracy. The reference is the app, not a calibrated
  instrument. Agreement with the app says the arithmetic is the same.
  It says nothing about how close the PPK2 is to the true current.
- Other units and other systems. The bench measurements were made on
  one PPK2, on a Mac. The package runs on Linux and Windows as well,
  where its unit tests pass. No capture has been compared there.
- Lost samples. Their handling is tested on streams built for the
  purpose and by freezing a capture on the bench, not against the app:
  this package differs from the app here on purpose.
