# Round of 2026-11-21: the app against `ppk2 capture`

One bench, captured by Nordic's
[Power Profiler app](https://docs.nordicsemi.com/r/bundle/nrf-connect-for-desktop/page/app/pc-nrfconnect-ppk/using_ppk_app.html) and by
`ppk2 capture` within minutes of each other, in both modes. See the
[results page](../../../docs/validation/results.md) of the
documentation for the setup, the tables and the plots.

This folder holds what they come from. `summary.txt` is what the
scripts print from the captures.

## Captures

The six captures weigh 42 MB. They are kept on the branch `captures`
of this repository, at commit `1f7d123`, so installing the package
does not download them. To put them in `captures/`, run:

```sh
just captures
```

or, without just, from the root of the repository:

```sh
git fetch origin captures
git archive FETCH_HEAD '*.csv.xz' | tar -x -C validation/evidence/bench_dut/captures
```

## Files

| File | Content |
|---|---|
| `captures/<mode>_app.csv.xz` | The app's export |
| `captures/<mode>_ppk2_1.csv.xz`, `captures/<mode>_ppk2_2.csv.xz` | The two captures of `ppk2 capture` |
| `ppk2_metadata.txt` | The output of `ppk2 metadata` on the PPK2 used |
| `summary.py`, `summary.txt` | The script that prints the figures of the results page, and what it printed |
| `make_plots.py`, `plots/` | The script that draws the plots, and the plots. `wakeup.png` shows two wake-ups, one with readings the spike filter left in |

## Reproduction

With the captures in place, run:

```sh
uv run --group validation python validation/evidence/bench_dut/summary.py
just plots
python validation/regions.py validation/evidence/bench_dut/captures/source_app.csv.xz
```

`summary.py` takes a few minutes: it reads 18 million rows. `just plots`
redraws the three figures with the versions fixed in `uv.lock`, and
prints the wake-up counts quoted on the Principle page.
