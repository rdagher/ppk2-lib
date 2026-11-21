# Round of 2026-11-21: the app against `ppk2 capture`

One bench, captured by Nordic's Power Profiler app and by
`ppk2 capture` within minutes of each other, in both modes. The
[results page](../../../docs/validation/results.md) of the
documentation discusses the numbers; this folder holds what they come
from.

The setup, the tables and the plots are on the results page. What the
scripts print from these captures is in `summary.txt`.

## Files

| File | Content |
|---|---|
| `captures/<mode>_app.csv.xz` | The app's export |
| `captures/<mode>_ppk2_1.csv.xz`, `captures/<mode>_ppk2_2.csv.xz` | The two captures of `ppk2 capture` |
| `ppk2_metadata.txt` | The output of `ppk2 metadata` on the PPK2 used |
| `summary.py`, `summary.txt` | The script that prints the tables above, and what it printed |
| `make_plots.py`, `plots/` | The script that draws the plots, and the plots. `wakeup.png` shows two wake-ups, one with readings the spike filter left in |

## Reproduction

```sh
uv run --group validation python validation/evidence/bench_dut/summary.py
just plots
python validation/regions.py validation/evidence/bench_dut/captures/source_app.csv.xz
```

`summary.py` takes a few minutes: it reads 18 million rows. `just plots`
redraws the three figures with the versions fixed in `uv.lock`, and
prints the wake-up counts quoted on the Principle page.
