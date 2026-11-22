#!/usr/bin/env python3
"""Print the tables of this round from the six captures in ``captures/``.

Per mode: the current and the charge of the regions marked by D0 and
D1 in each capture, the difference of each ``ppk2 capture`` from the
app's capture, and the Kolmogorov-Smirnov (KS) statistic between the
distributions of the current, D0 high and D0 low apart. Also the 0.2 µA
floor: no value of a capture may lie between 0 and 0.2 µA.

Run from the repository root (numpy comes with the validation group)::

    uv run --group validation python validation/evidence/bench_dut/summary.py
"""

import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
from regions import collect_pulses, load, powered  # noqa: E402

SKIP = 200_000  # samples: the 2 s after power-on, which hold the boot
WINDOW = 2_600_000  # samples: the same 26 s in every capture


def ks_statistic(a: np.ndarray, b: np.ndarray) -> float:
    """Two-sample KS statistic: the largest gap between the two ECDFs."""
    xa, xb = np.sort(a), np.sort(b)
    grid = np.concatenate([xa, xb])
    ecdf_a = np.searchsorted(xa, grid, side="right") / len(xa)
    ecdf_b = np.searchsorted(xb, grid, side="right") / len(xb)
    return float(np.max(np.abs(ecdf_a - ecdf_b)))


def measure(name: str) -> dict[str, object]:
    """Region figures and the post-boot window of one capture."""
    everything = load(HERE / "captures" / f"{name}.csv.xz")
    currents = np.array([row[1] for row in everything])
    rows = powered(everything)
    d0 = collect_pulses(rows, 0)
    d1 = collect_pulses(rows, 1)
    start_ms = d0[0].start_s * 1000.0
    idle = [ua for t, ua, a, b in rows if t > start_ms and not a and not b]
    window = np.array([(ua, a) for _, ua, a, _ in rows[SKIP : SKIP + WINDOW]])
    return {
        "n0": len(d0),
        "i0": [p.charge_uc / p.duration_s for p in d0],
        "q0": [p.charge_uc for p in d0],
        "n1": len(d1),
        "i1": [p.charge_uc / p.duration_s for p in d1],
        "q1": [p.charge_uc for p in d1],
        "idle": statistics.median(idle),
        "zeros": float(np.mean(currents == 0.0) * 100),
        "below_floor": int(np.sum((currents > 0.0) & (currents < 0.2))),
        "negative": int(np.sum(currents < 0.0)),
        "lowest": float(currents[currents > 0.0].min()),
        "ua": window[:, 0],
        "d0": window[:, 1] == 1,
    }


def mean_sd(values: list[float]) -> str:
    """``mean ± standard deviation``."""
    return f"{statistics.fmean(values):.2f} ± {statistics.stdev(values):.2f}"


def percent(ours: list[float], app: list[float]) -> str:
    """Difference of the means, as a share of the second."""
    return (
        f"{abs(statistics.fmean(ours) - statistics.fmean(app)) / statistics.fmean(app) * 100:.2f} %"
    )


def main() -> None:
    """Print the tables of both modes."""
    for mode in ("ampere", "source"):
        app, first, second = (measure(f"{mode}_{k}") for k in ("app", "ppk2_1", "ppk2_2"))
        print(f"== {mode} meter mode")
        print(f"{'':28}{'app':>20}{'ppk2 capture 1':>20}{'ppk2 capture 2':>20}")
        rows = (
            ("D0 regions", lambda m: str(m["n0"])),
            ("current of a D0 region, µA", lambda m: mean_sd(m["i0"])),
            ("charge of a D0 region, µC", lambda m: mean_sd(m["q0"])),
            ("D1 regions", lambda m: str(m["n1"])),
            ("current of a D1 region, µA", lambda m: mean_sd(m["i1"])),
            ("charge of a D1 region, µC", lambda m: mean_sd(m["q1"])),
            ("idle median, µA", lambda m: f"{m['idle']:.2f}"),
            ("samples at zero, %", lambda m: f"{m['zeros']:.3f}"),
            ("between 0 and 0.2 µA", lambda m: str(m["below_floor"])),
            ("negative", lambda m: str(m["negative"])),
            ("lowest above zero, µA", lambda m: f"{m['lowest']:.3f}"),
        )
        for label, cell in rows:
            print(f"{label:28}{cell(app):>20}{cell(first):>20}{cell(second):>20}")
        for label, key in (
            ("D0 current", "i0"),
            ("D0 charge", "q0"),
            ("D1 current", "i1"),
            ("D1 charge", "q1"),
        ):
            print(
                f"difference from the app, {label}: capture 1 {percent(first[key], app[key])}, "
                f"capture 2 {percent(second[key], app[key])}; "
                f"between the two captures {percent(second[key], first[key])}"
            )
        for label, m in (("capture 1", first), ("capture 2", second)):
            both = ks_statistic(m["ua"], app["ua"])
            high = ks_statistic(m["ua"][m["d0"]], app["ua"][app["d0"]])
            low = ks_statistic(m["ua"][~m["d0"]], app["ua"][~app["d0"]])
            mean = abs(m["ua"].mean() - app["ua"].mean()) / app["ua"].mean() * 100
            print(
                f"26 s after boot, {label} against the app: means {mean:.2f} % apart, "
                f"KS {both:.4f}, D0 high {high:.4f}, D0 low {low:.4f}"
            )
        print()


if __name__ == "__main__":
    main()
