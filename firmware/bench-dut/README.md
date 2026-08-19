# PPK2 bench-DUT (nRF54LM20 / nRF54L15 / nRF52840 DKs)

Deterministic reference firmware for the HIL test bench. Toggles two
GPIOs at fixed rates so the PPK2's logic-channel decode can be
validated end-to-end against a signal whose timing is known by
construction:

| PPK2 channel | Frequency | Period | Duty |
|---|---|---|---|
| D0 | 5 Hz | 200 ms | 50 % |
| D1 | 0.5 Hz | 2 s | 50 % |

Implementation: two Zephyr `k_timer`s firing from the system tick;
toggles run in ISR context so there's no scheduler jitter on the
edges. The main thread sleeps forever once the timers are armed.

One source tree, three supported dev kits — the board overlays under
`boards/` differ only in pin assignment:

| Dev kit | Board target | D0 pin | D1 pin | Pin rationale |
|---|---|---|---|---|
| nRF54LM20DK | `nrf54lm20dk/nrf54lm20b/cpuapp` | P1.12 | P1.13 | Expansion-header pins, bench-validated against button-line conflicts on this DK revision. |
| nRF54L15DK (PCA10156) | `nrf54l15dk/nrf54l15/cpuapp` | P1.11 | P1.12 | Routed to the GPIO connectors (HW UG 4503_209); P1.11 claimed only by the disabled `spi22` pinctrl group, P1.12 unclaimed. Avoids LEDs, buttons, and the uart20 console pins. |
| nRF52840 DK (PCA10056) | `nrf52840dk/nrf52840` | P0.28 (A2) | P0.29 (A3) | Arduino R3 analog header; P0.29 claimed only by the disabled `spi0` group. Validated against the PCA10056 schematic. |

Hex images are build artefacts, not committed: build them locally
with `just hex [BOARD]` (a CI build matrix producing per-board hexes
as release artifacts is planned). The builds are reproducible — the
same source + NCS toolchain version yields byte-identical hexes.

Verification status: the nRF54LM20DK image is bench-verified against
a PPK2 capture (D0/D1 edge rates measured at 5.00 Hz / 0.50 Hz). The
nRF54L15 and nRF52840 pin choices are verified against the board DTS
and hardware documentation but have not yet been through a PPK2
capture — run the "Verifying the trace" check below on first use.

## Wiring

PPK2 in ammeter mode, in series with the DK's VDD rail. Logic wires
(pick the pin pair for your DK from the table above):

```
PPK2 D0  ←  DK <D0 pin>  (toggle every 100 ms → 5 Hz)
PPK2 D1  ←  DK <D1 pin>  (toggle every 1000 ms → 0.5 Hz)
PPK2 GND ←  DK GND
PPK2 VCC ←  DK VDD rail  (logic-level reference for D0-D7)
```

## Building

Requires the Nordic NCS toolchain. The recipes assume an NCS
install managed by nrfutil (`/opt/nordic/ncs`); `NCS_VERSION` / `NCS_WORKSPACE` override.

```sh
just build [BOARD]   # ./build/<dk>/ — full Zephyr build tree
just hex [BOARD]     # ./bench-dut-<dk>.hex — canonical artefact
just hex-all         # rebuild all three hexes
just flash [BOARD]   # program the connected DK
just clean           # wipe ./build/
just which           # print resolved settings
```

`BOARD` is a full Zephyr board target (see the table above); it
defaults to the nRF54LM20DK. Examples:

```sh
just build nrf52840dk/nrf52840
just flash nrf52840dk/nrf52840
DK_SERIAL=<serial> just flash nrf52840dk/nrf52840   # serial from `nrfutil device list`
```

The hex this firmware produces can also be flashed via the standard
`nrfutil device program` invocation pointed at the built
`bench-dut-<dk>.hex` (or `build/<dk>/merged.hex`), without going
through `just`.

## Verifying the trace

Once the DK is running, `ppk2 capture --seconds 30 --out trace.csv`
should produce a CSV where:

- `D0` toggles every ~100 ms (5 Hz square wave).
- `D1` toggles every ~1000 ms (0.5 Hz square wave).
- Mean current is the DK's idle draw plus the two GPIO drivers'
  switching contribution (negligible at these rates).

The `validation/compare_cli.py` harness can diff a capture of this
signal against a stored baseline capture (or use
`validation/cross_validate.py` to record both sides back-to-back).

## License

Apache-2.0 OR MIT — matches the top-level repo. Zephyr's own license
covers anything pulled in by the build (Apache-2.0).
