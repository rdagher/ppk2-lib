# Results

What the three levels of the [method](method.md) found.

| Level | Result | Run on |
|---|---|---|
| The parser, 600 samples | Every current equal to three decimals, every digital byte identical | The current code |
| Noise floor, 60 s | Same header, same distribution (KS 0.0002) | The build of 2026-07-17 |
| Workload on an nRF52840 DK | Current per marked region within 0.27 %, charge within 0.31 % | The build of 2026-08-19 |
| Workload on an nRF54LM20 DK | Current per marked region within 0.05 %, charge within 0.03 % | The build of 2026-08-19 |
| Ten hardware tests | All pass | The current code, 2026-11-20 |

## Parser

On the 600 recorded samples, this package and the app's parser give
the same current to three decimals for every sample, and the same
digital inputs. The stream crosses all five measurement ranges, so the
calibration of each range and the spike filter are part of what agrees.

## Noise floor

A PPK2 in Ampere meter mode with nothing connected, 60 s with each
tool. The app reports any current below 0.2 µA as zero, and so must
`ppk2 capture`.

| Capture | Samples at zero | Samples above zero | Their maximum | Their mean | Negative | Between 0 and 0.2 µA |
|---|---:|---:|---:|---:|---:|---:|
| App | 99.852 % | 8,880 | 0.347 µA | 0.240 µA | 0 | 0 |
| `ppk2 capture` | 99.868 % | 7,955 | 0.435 µA | 0.241 µA | 0 | 0 |

The headers are identical and the KS statistic between the two is
0.0002. The few samples above the floor are noise spikes, and their
number varies from one capture to the next. The two files of this round
were too large to keep; the comparison report is stored.

## Workload firmware

The same firmware on two dev kits, captured for about 30 s with each
tool. It raises D0 around a 600 ms workload and D1 around a sweep of
ten workloads.

### nRF52840 DK, Source meter mode at 3.0 V

| | App | `ppk2 capture` | Difference |
|---|---|---|---|
| D0 workloads | 31, 596.96 ms wide | 31, 596.69 ms wide | |
| Current of a D0 workload | 3,760.2 ± 2.5 µA | 3,751 ± 11 µA | 0.23 % |
| Charge of a D0 workload | 2,244.7 ± 1.4 µC | 2,238.5 ± 6.6 µC | 0.28 % |
| D1 sweeps | 3, 7,470.81 ms wide | 3, 7,468.04 ms wide | |
| Current of a D1 sweep | 3,135.1 ± 1.6 µA | 3,126.50 ± 0.70 µA | 0.27 % |
| Charge of a D1 sweep | 23,421 ± 13 µC | 23,348.8 ± 2.6 µC | 0.31 % |
| Pulses at boot | 3 | 3 | |
| Idle mean | 646.01 µA | 636.86 µA | 1.4 % |

The current of a region is its mean current, and its charge is that
current added up over its width. Each is given as the mean ± the
standard deviation over the regions. The difference is that of the
means, `ppk2 capture` against the app, as a share of the app's,
computed before rounding.

After the first 2.5 s, the KS statistic inside the workload is 0.0253,
with means of 3,760.6 and 3,752.5 µA. At idle it is 0.1460: the idle
level moved by about 9 µA in the minutes between the two captures.

Over the whole trace, the means are 0.51 % apart and the KS statistic
is 0.0506, just over the 0.05 limit. That is the effect of the two
levels and of the idle drift, which is why the round is judged per
region.

![Both captures of the nRF52840 DK, overlaid, and the distribution of the current per region](../img/parity_nrf52840.png)

### nRF54LM20 DK, Ampere meter mode at 3.3 V

| | App | `ppk2 capture` | Difference |
|---|---|---|---|
| D0 workloads | 30, 599.71 ms wide | 31, 599.97 ms wide | |
| Current of a D0 workload | 1,445.6 ± 1.3 µA | 1,445.4 ± 1.9 µA | 0.01 % |
| Charge of a D0 workload | 866.93 ± 0.73 µC | 867.2 ± 1.2 µC | 0.03 % |
| D1 sweeps | 3, 7,497.86 ms wide | 3, 7,500.58 ms wide | |
| Current of a D1 sweep | 1,159.67 ± 0.63 µA | 1,159.0 ± 1.1 µA | 0.05 % |
| Charge of a D1 sweep | 8,695.1 ± 4.6 µC | 8,693.5 ± 8.3 µC | 0.02 % |
| Idle median | 4.25 µA | 4.29 µA | |

After the first 2.5 s, the KS statistic is 0.0065 inside the workload
and 0.0091 at idle. Over the whole trace the means are 0.35 % apart and
the KS statistic is 0.0048.

![Both captures of the nRF54LM20 DK, overlaid, and the distribution of the current per region](../img/parity_nrf54lm20.png)

## Hardware tests

All ten pass. They were last run on 2026-11-20 with the current code,
in Source meter mode at 3.3 V on an nRF54LM20 DK. The run in Ampere
meter mode of the same day predates the last changes to how a session
closes.

## Differences from the app

On purpose, and outside what the comparisons above exercise:

- Lost samples. The app's code duplicates held samples, counts a lost
  gap one short, and places the samples received after a gap before
  it. This package emits each sample once, counts the full gap, and
  keeps the order. The
  [protocol page](../measure/protocol.md#5-stream-reassembly)
  has the four points with their line references. Both record a lost
  sample as 0.2 µA.
- Where a capture starts. In the app you start the capture and enable
  power by hand. `ppk2 capture` does both, and its file begins about
  10 ms before the power comes up.

And one comparison that has not been made: a `.ppk2` file written by
this package has not yet been opened in the app.

## Limitations

- One PPK2, under macOS.
- The reference is the app. Agreement with it says nothing about the
  absolute accuracy of the PPK2, which Nordic gives as better than
  ±20 %.
- The whole-capture rounds were taken with the builds of their day,
  three and four months before this release. The parser check and the
  hardware tests run on the current code. A fresh round with the
  current build is still to be done.

## Reproducing the results

The captures, the firmware and the scripts of the rounds are in
[`validation/evidence/`](https://github.com/rdagher/ppk2-lib/tree/main/validation/evidence),
the recording and its reference in
[`tests/fixtures/`](https://github.com/rdagher/ppk2-lib/tree/main/tests/fixtures).
From a checkout:

```sh
# the parser against the stored reference
just test

# current and charge per marked region of a stored capture
python validation/evidence/trace_demo/firmware/attribute.py \
    validation/evidence/trace_demo/captures/nrf54lm20_ampere_cli.csv.gz

# the plots above, and the KS statistic and mean per region
just plots

# two captures of your own bench
uv run --group validation python -m validation.compare_cli app.csv ours.csv --skip-initial-s 2
```
