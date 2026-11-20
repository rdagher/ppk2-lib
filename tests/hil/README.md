# Hardware tests

These tests need a bench: one PPK2 and a dev kit running the
[`bench-dut`](bench-dut/) firmware, which toggles D0 at 5 Hz and D1 at
0.5 Hz and runs a workload while D0 is high. Its
[README](bench-dut/README.md) has the wiring and the flash recipe.

```sh
just test-hw                          # Ampere meter mode: PPK2 in series with the kit's own supply
PPK2_HIL_SOURCE_MV=3300 just test-hw  # Source meter mode: PPK2 powers the kit at 3.3 V
```

`just test` and `just ci` skip them: they carry the `hardware` marker.
