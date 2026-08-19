#!/usr/bin/env python3
"""Attribute captured energy to the demo firmware's trace markers.

Reads a GUI-parity CSV (from ``ppk2 capture`` or a Nordic GUI export)
and integrates energy over the regions the firmware marks:

- D0 high — one busy-blink workload (the 3-pulse boot sync burst is
  detected and reported separately by its < 5 ms width).
- D1 high — one full sweep of workloads.
- Neither high — idle (gaps + inter-sweep rest).

Energy per region is the charge integral times VDD: each row is one
10 µs sample, so E = sum(I_µA) * 10 µs * VDD. Stdlib only.

Usage:
    python attribute.py trace.csv --vdd 3.0
"""

import argparse
import csv
import gzip
import statistics
from dataclasses import dataclass
from pathlib import Path

SAMPLE_PERIOD_S = 10e-6  # 100 kSPS
SYNC_PULSE_MAX_S = 0.005  # D0 pulses shorter than this are the boot sync burst
POWER_ON_UA = 200.0  # rail-up detection: logic pins float while the DUT is unpowered


@dataclass
class Pulse:
    """One contiguous high region of a logic pin."""

    start_s: float
    duration_s: float
    charge_uc: float  # integral of current over the pulse, in µC

    def energy_uj(self, vdd_v: float) -> float:
        """Energy over the pulse in µJ (charge x VDD)."""
        return self.charge_uc * vdd_v


def collect_pulses(rows: list[tuple[float, float, int, int]], pin: int) -> list[Pulse]:
    """Walk the samples once, closing a Pulse at each falling edge of `pin`.

    A pulse only opens on a real rising edge — a pin already high at
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


def stats_line(name: str, pulses: list[Pulse], vdd_v: float) -> str:
    """One report row: count, energy mean ± std, mean width."""
    energies = [p.energy_uj(vdd_v) for p in pulses]
    durations = [p.duration_s * 1000.0 for p in pulses]
    mean_e = statistics.fmean(energies)
    sd_e = statistics.stdev(energies) if len(energies) > 1 else 0.0
    return (
        f"{name:<22} n={len(pulses):<4} "
        f"energy {mean_e:9.2f} ± {sd_e:6.2f} µJ   "
        f"width {statistics.fmean(durations):8.2f} ms"
    )


def main() -> None:
    """Parse the CSV, split pulses per marker, print the report."""
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("csv_path", help="GUI-parity capture CSV")
    ap.add_argument("--vdd", type=float, default=3.0, help="DUT VDD in volts (default 3.0)")
    args = ap.parse_args()

    rows: list[tuple[float, float, int, int]] = []
    path = Path(args.csv_path)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            rows.append(
                (
                    float(rec["Timestamp(ms)"]),
                    float(rec["Current(uA)"]),
                    int(rec["D0"]),
                    int(rec["D1"]),
                )
            )
    if not rows:
        raise SystemExit("empty capture")

    # Boot-inclusive captures begin before the rail comes up; while the
    # DUT is unpowered its logic reference floats and D0/D1 read as
    # garbage. Start attribution at the first sample with real current.
    power_i = next((i for i, r in enumerate(rows) if r[1] > POWER_ON_UA), 0)
    if power_i:
        print(f"pre-power region skipped: {rows[power_i][0] / 1000.0:.3f} s")
        rows = rows[power_i:]

    d0 = collect_pulses(rows, 0)
    sync = [p for p in d0 if p.duration_s < SYNC_PULSE_MAX_S]
    workloads = [p for p in d0 if p.duration_s >= SYNC_PULSE_MAX_S]
    sweeps = collect_pulses(rows, 1)

    total_s = (rows[-1][0] - rows[0][0]) / 1000.0
    # Idle floor: exclude the boot region (rail-up to the end of the
    # sync burst / first workload), which otherwise pollutes the stats
    # with run-level boot current.
    boot_end_ms = (workloads[0].start_s * 1000.0) if workloads else 0.0
    idle_ua = [ua for t, ua, d0v, d1v in rows if t > boot_end_ms and not d0v and not d1v]

    print(f"capture: {len(rows)} samples, {total_s:.2f} s, VDD {args.vdd:.2f} V")
    if sync:
        print(f"boot sync burst: {len(sync)} short D0 pulses (t={sync[0].start_s:.3f} s)")
    if workloads:
        print(stats_line("D0 workloads", workloads, args.vdd))
    if sweeps:
        print(stats_line("D1 sweeps", sweeps, args.vdd))
    if idle_ua:
        print(
            f"{'idle (no marker)':<22} median "
            f"{statistics.median(idle_ua):9.2f} µA   mean {statistics.fmean(idle_ua):9.2f} µA"
        )


if __name__ == "__main__":
    main()
