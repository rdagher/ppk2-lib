#!/usr/bin/env python3
"""Current and charge of the regions a firmware marks with D0 and D1.

Reads a capture in the app's CSV format, from ``ppk2 capture`` or
exported from Nordic's app, plain or compressed (``.gz``, ``.xz``):

- D0 high and D1 high: the regions the firmware marks.
- Neither high: idle.

The charge of a region is the integral of its current: each row is one
10 µs sample, so Q = sum(I_µA) * 10 µs, in µC. Its current is that
charge over its width. The PPK2 measures current only, so no energy is
reported: that would need the voltage at the DUT, which is not in the
capture. Stdlib only.

The spread after ± is the standard deviation over the regions, given to
two significant digits, with the mean rounded to the same place.

Usage:
    python validation/regions.py trace.csv
"""

import argparse
import csv
import gzip
import lzma
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

SAMPLE_PERIOD_S = 10e-6  # 100 kSPS
POWER_ON_UA = 200.0  # rail-up detection: logic pins float while the DUT is unpowered


@dataclass
class Pulse:
    """One contiguous high region of a logic pin."""

    start_s: float
    duration_s: float
    charge_uc: float  # integral of current over the pulse, in µC


Row = tuple[float, float, int, int]  # timestamp in ms, current in µA, D0, D1


def load(path: Path) -> list[Row]:
    """Read the timestamp, the current, D0 and D1 of a capture."""
    opener = {".gz": gzip.open, ".xz": lzma.open}.get(path.suffix, open)
    with opener(path, "rt", newline="") as f:
        return [
            (float(rec["Timestamp(ms)"]), float(rec["Current(uA)"]), int(rec["D0"]), int(rec["D1"]))
            for rec in csv.DictReader(f)
        ]


def powered(rows: list[Row]) -> list[Row]:
    """The rows from the first one with real current on.

    Before the DUT is powered its logic reference floats, and D0 and D1
    read as garbage.
    """
    start = next((i for i, row in enumerate(rows) if row[1] > POWER_ON_UA), 0)
    return rows[start:]


def collect_pulses(rows: list[Row], pin: int) -> list[Pulse]:
    """Walk the samples once, closing a Pulse at each falling edge of `pin`.

    A pulse only opens on a real rising edge: a pin already high at
    the first sample is ignored (its start is unknown), just like a
    pulse still high at the last sample (its end is unknown).
    """
    pulses: list[Pulse] = []
    high = False
    seen_low = False
    start_s = 0.0
    charge_uc = 0.0
    for t_ms, ua, d0, d1 in rows:
        level = (d0, d1)[pin]
        if level and not high and seen_low:
            high, start_s, charge_uc = True, t_ms / 1000.0, 0.0
        if high:
            charge_uc += ua * SAMPLE_PERIOD_S
        if not level:
            seen_low = True
            if high:
                high = False
                pulses.append(Pulse(start_s, t_ms / 1000.0 - start_s, charge_uc))
    return pulses


def _mean_sd(values: list[float]) -> str:
    """``mean ± standard deviation``: two significant digits for the spread."""
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    places = max(0, 1 - math.floor(math.log10(sd))) if sd > 0 else 2
    return f"{mean:.{places}f} ± {sd:.{places}f}"


def stats_line(name: str, pulses: list[Pulse]) -> str:
    """One report row: count, then mean ± standard deviation of current and charge, mean width."""
    currents = [p.charge_uc / p.duration_s for p in pulses]  # µC / s = µA
    charges = [p.charge_uc for p in pulses]
    durations = [p.duration_s * 1000.0 for p in pulses]
    return (
        f"{name:<14} n={len(pulses):<3} "
        f"current {_mean_sd(currents)} µA   "
        f"charge {_mean_sd(charges)} µC   "
        f"width {statistics.fmean(durations):.2f} ms"
    )


def main() -> None:
    """Print the report of a capture."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("csv_path", help="a capture in the app's CSV format")
    args = ap.parse_args()

    rows = load(Path(args.csv_path))
    if not rows:
        raise SystemExit("empty capture")

    skipped = len(rows) - len(powered(rows))
    if skipped:
        print(f"pre-power region skipped: {rows[skipped][0] / 1000.0:.3f} s")
        rows = powered(rows)

    d0 = collect_pulses(rows, 0)
    d1 = collect_pulses(rows, 1)

    total_s = (rows[-1][0] - rows[0][0]) / 1000.0
    # Idle: from the first marked region on, which leaves the boot out.
    boot_end_ms = (d0[0].start_s * 1000.0) if d0 else 0.0
    idle_ua = [ua for t, ua, d0v, d1v in rows if t > boot_end_ms and not d0v and not d1v]

    print(f"capture: {len(rows)} samples, {total_s:.2f} s")
    if d0:
        print(stats_line("D0 regions", d0))
    if d1:
        print(stats_line("D1 regions", d1))
    if idle_ua:
        print(
            f"{'idle (no marker)':<22} median "
            f"{statistics.median(idle_ua):9.2f} µA   mean {statistics.fmean(idle_ua):9.2f} µA"
        )


if __name__ == "__main__":
    main()
