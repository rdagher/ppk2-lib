# Bench firmware

A small Zephyr application that gives the hardware tests a signal
whose timing is known in advance.

| PPK2 input | Frequency | High for |
|---|---|---|
| D0 | 5 Hz | 100 ms |
| D1 | 0.5 Hz | 1 s |

Two kernel timers toggle the pins from interrupt context, so the edges
do not depend on the scheduler. The main thread spins while D0 is high
and sleeps while it is low.

So the current has two levels that follow D0. On the nRF54LM20 DK at
3.3 V:

- the high level is about 1.4 mA;
- the low level is 1.4 µA in the median. Its mean is 15 µA, the boot
  and the wake-ups included.

## Dev kits


| Dev kit | Board target | D0 | D1 |
|---|---|---|---|
| nRF54LM20 DK | `nrf54lm20dk/nrf54lm20b/cpuapp` | P1.12 | P1.13 |
| nRF54L15 DK | `nrf54l15dk/nrf54l15/cpuapp` | P1.11 | P1.12 |
| nRF52840 DK | `nrf52840dk/nrf52840` | P0.28 (A2) | P0.29 (A3) |

The overlays in [`boards/`](boards/) differ only in these pins. The
nRF54LM20 DK build is the one measured on a bench. The nRF52840 pins
were used with another firmware, and the nRF54L15 pins were only
checked against the board files: verify the signal before relying on
either.

## Wiring

Connect the logic port of the PPK2:

```text
D0   to the dev kit's D0 pin
D1   to the dev kit's D1 pin
GND  to the dev kit's ground
VCC  to the dev kit's VDD (the level reference for the inputs)
```

Then put the PPK2 in the dev kit's supply, in Ampere meter or Source
meter mode.

## Building and flashing

You need the toolchain of the
[nRF Connect SDK](https://github.com/nrfconnect/sdk-nrf) installed by
nrfutil, under `/opt/nordic/ncs`. The firmware is built and tested
with SDK v3.3.1. `NCS_VERSION` and `NCS_WORKSPACE` override the
defaults. Run these from this folder:

```sh
just build [BOARD]   # build/<dk>/
just hex [BOARD]     # bench-dut-<dk>.hex
just flash [BOARD]   # program the connected kit
just clean
```

`BOARD` is one of the targets above. By default, it is the nRF54LM20
DK. If several kits are attached, pick one with `DK_SERIAL=<serial>`.
CI builds the three images on every firmware change.

If the PPK2 powers the dev kit, the kit is off until a command turns
it on: flash with `ppk2 run --source --vdd 3.3 -- just flash`.

## Signal check

```sh
ppk2 capture --seconds 30 --out trace.csv
```

D0 should change every 100 ms and D1 every second, and the current
should step with D0.
