# Validation

Scripts that compare captures of the same bench: one made by this tool
against one exported from Nordic's Power Profiler app, or two builds of
this tool against each other.

## Comparing two captures

```sh
uv run --group validation python -m validation.compare_cli a.csv b.csv \
    --label-a "this build" --label-b "app export" --out report.md
```

The report gives, for both files:

- the header and the sample rate,
- the mean, standard deviation and maximum of the current,
- a two-sample Kolmogorov-Smirnov (KS) test on the current,
- the duty cycle and edge rate of each digital input.

The exit code is 0 when:

- the headers are identical,
- the mean currents are within 1 % of each other,
- the KS statistic is below 0.05.

## Capturing twice and comparing

```sh
uv run --group validation python -m validation.cross_validate \
    --binary-a $(which ppk2) --binary-b /path/to/other/ppk2 \
    --seconds 60
```

This runs both binaries one after the other on the bench that is
plugged in, then compares the two files. Both must accept `capture
--out PATH --seconds N` and write the CSV described in the
[file formats](../docs/measure/formats.md#csv) page. Run it from the
repository root. The captures are taken in Ampere meter mode.

## Limits of the 1 % rule

The 1 % limit on the mean suits a device under test (DUT) that spends
its time in a workload. It is too tight in two cases:

- A capture that starts at power-on contains the boot inrush, which
  can dominate a small mean. Skip it with `--skip-initial-s 2`.
- A DUT idling at a few µA, where two identical runs can differ by
  more than 1 %. Measure that spread with two runs of the same binary
  and set `--mean-tolerance-pct` from it, or rely on the header, the KS
  test and the pin rates.

A signal with two levels is also sensitive to where each capture
starts in the cycle. Compare it level by level, as the
[round of this release](evidence/bench_dut/README.md) does, with
`validation/regions.py`.

## Evidence

- [`bench_dut/`](evidence/bench_dut/README.md): the round of this
  release. The app against `ppk2 capture` in both modes on an
  nRF54LM20 DK, with the way to the six captures, the versions used,
  and the scripts that print the tables and draw the plots.

Its DUT runs the [bench firmware](../tests/hil/bench-dut/) of the
hardware tests, which gives a known signal on D0 and D1.

The parser itself is checked separately, sample by sample, against
Nordic's parser: see [`tests/fixtures/`](../tests/fixtures/README.md).
