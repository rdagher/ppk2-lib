# Method

The claim this package makes is narrow: on the same PPK2 and the same
bench, it gives the numbers that Nordic's Power Profiler app gives. The
app is the reference throughout. This page says how the claim is
tested; the [results](results.md) are on the next one.

It is tested at three levels, from one sample to a whole bench:

| Level | What is compared | Against | Material |
|---|---|---|---|
| The parser | 600 recorded samples, one by one | The app's own parsing code | `tests/fixtures/` |
| Whole captures | Two captures of one bench, taken back to back | The app's CSV export | `validation/` |
| A bench | What the tool reads from a signal known in advance | The bench firmware | `tests/hil/` |

## Parser comparison

The recording is `stream_poweron.bin`: 600 samples, 6 ms, taken while a
PPK2 powered an nRF54LM20 DK on in Source meter mode at 3.3 V. The
current climbs through all five measurement ranges and changes range
nine times. The calibration text of the same PPK2 is stored next to it.

The reference is `parsed_poweron.csv`: the output of the app's parser
for those bytes. It was produced by running the app's code outside the
app (`pc-nrfconnect-ppk` v4.4.1, `src/device/serialDevice.ts`), with a
small Node script. To produce it again:

```sh
git clone https://github.com/nordicsemi/pc-nrfconnect-ppk
node tests/fixtures/make_reference.mjs pc-nrfconnect-ppk
```

The app's source is not copied into this repository: its licence
allows using it, not redistributing it.

A unit test parses the same bytes with this package. It passes when
every current agrees to the three decimals the reference carries, and
every byte of digital inputs is identical.

This covers the extraction of the fields, the calibration of each
range, and the spike filter across range changes. It does not cover
lost samples: the recording has none. Those cases are tested on streams
built for the purpose, and there this package differs from the app on
purpose. The [results](results.md#differences-from-the-app)
list the differences.

## Capture comparison

A round compares one capture made by the app with one made by
`ppk2 capture`, on a bench that is not touched in between.

### Procedure

1. Set up the bench once: the DUT, its firmware, the wiring, the mode
   and the supply voltage. Note the position of every switch.
2. In the app: Start, then Enable power output. Stop after about 30 s.
   Save / Export to CSV at 100,000 samples per second.
3. Quit the app. Only one program can hold the PPK2.
4. Capture the same duration with `ppk2 capture`, in the same mode and
   at the same voltage.
5. Compare the two files.

Both captures begin at power-on, so the DUT boots in both.

### Compared quantities

`validation/compare_cli.py` reads the two files and reports:

- the header, which must be identical;
- the sample rate;
- the mean, standard deviation and maximum of the current;
- the Kolmogorov-Smirnov (KS) statistic between the two distributions;
- the duty cycle and edge rate of each digital input.

It passes when the headers are identical, the means are within 1 % and
the KS statistic is below 0.05.

For a firmware that marks its work with D0 and D1, a second script,
`attribute.py`, computes the current, the charge, the number and the
width of the
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
- An idle current drifts over minutes. Two identical runs of one tool
  on an idle DUT at a few tens of µA differed by 2 to 3 %.

So a round is judged region by region. For each marked region the
mean current is compared, and the charge, which is that current added
up over the region's duration. The distribution of the current inside
the workload and inside the idle is compared as well. There is no
energy in the comparison, because a PPK2 measures current only.

## Hardware tests

The hardware tests do not compare with the app. They check the tool
against a signal that is known in advance, from the firmware in
`tests/hil/bench-dut`. D0 toggles at 5 Hz and D1 at 0.5 Hz. The CPU is
busy while D0 is high, so the current steps with D0.

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

```sh
just test-hw                          # Ampere meter mode
PPK2_HIL_SOURCE_MV=3300 just test-hw  # Source meter mode at 3.3 V
```

## Limitations

- Absolute accuracy. The reference is the app, not a calibrated
  instrument. Agreement with the app says the arithmetic is the same;
  it says nothing about how close the PPK2 is to the true current.
- Other units and other systems. Everything was measured on one PPK2,
  under macOS.
- Lost samples on real hardware. Their handling is tested on
  constructed streams only.
