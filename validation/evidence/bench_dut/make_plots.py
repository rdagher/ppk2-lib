#!/usr/bin/env python3
"""Draw the plots of this round from the captures in ``captures/``.

One figure per mode: the app's capture and the first ``ppk2 capture``
overlaid from power-on, and the distribution of the current with D0
high and with D0 low. One more shows two wake-ups of the DUT, one with
a reading the spike filter left in. The figures are also copied to ``docs/img/``,
where the documentation site reads them. Run from the repository root::

    just plots
"""

import shutil
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
SITE_IMAGES = HERE.parents[2] / "docs" / "img"
sys.path.insert(0, str(HERE.parents[1]))
from regions import load, powered  # noqa: E402

SKIP = 200_000  # samples: the 2 s after power-on, which hold the boot
MODES = (
    ("ampere", "nRF54LM20 DK, Ampere meter mode, 3.3 V"),
    ("source", "nRF54LM20 DK, Source meter mode, 3.3 V"),
)
LABELS = (("app", "Power Profiler app"), ("ppk2_1", "ppk2 capture"))


def ecdf(ax: plt.Axes, samples: np.ndarray, label: str) -> None:
    """Plot the empirical CDF of ``samples``, thinned to 20,000 points."""
    xs = np.sort(samples)
    xs = xs[:: max(1, len(xs) // 20_000)]
    ax.plot(xs, np.arange(len(xs)) / len(xs), label=label, linewidth=1.2)


LEAK_UA = 20_000  # a sample above this at a wake-up is one the spike filter left in


def count_wakeups() -> None:
    """Print, per capture, the wake-ups and how many keep a sample above ``LEAK_UA``."""
    for name in ("source_ppk2_1", "source_app", "ampere_ppk2_1", "ampere_app"):
        rows = powered(load(HERE / "captures" / f"{name}.csv.xz"))
        ua = np.array([row[1] for row in rows])
        d0 = np.array([row[2] for row in rows]) == 1
        edges = np.nonzero(d0[1:] & ~d0[:-1])[0] + 1
        edges = edges[(edges > SKIP) & (edges < len(ua) - 400)]
        leaked = sum(ua[e - 300 : e + 300].max() > LEAK_UA for e in edges)
        print(f"{name}: {len(edges)} wake-ups, {leaked} with a sample above 20 mA")


def wakeups(out_dir: Path) -> None:
    """Two wake-ups of one capture: one clean, one with readings the filter left in."""
    rows = powered(load(HERE / "captures" / "source_ppk2_1.csv.xz"))
    ua = np.array([row[1] for row in rows])
    d0 = np.array([row[2] for row in rows]) == 1
    edges = np.nonzero(d0[1:] & ~d0[:-1])[0] + 1
    edges = edges[(edges > SKIP) & (edges < len(ua) - 100)]
    highest = np.array([ua[e - 100 : e + 100].max() for e in edges])
    picks = (
        (edges[highest < 5_000][0], "wake-up read correctly", "#2a78d6"),
        (edges[highest > 20_000][0], "wake-up with readings the spike filter left in", "#eb6834"),
    )
    fig, ax = plt.subplots(figsize=(9, 4.2))
    x = np.arange(-100, 100) * 0.01
    for edge, label, colour in picks:
        ax.step(
            x,
            np.maximum(ua[edge - 100 : edge + 100], 0.1),
            where="post",
            label=label,
            color=colour,
            linewidth=1.4,
        )
    ax.set_yscale("log")
    ax.set_xlabel("time from the rising edge of D0 (ms)")
    ax.set_ylabel("current (µA, log)")
    ax.set_title("Two wake-ups of the same DUT in one capture, 10 µs per sample", loc="left")
    ax.grid(True, which="major", alpha=0.3)
    ax.legend(loc="lower right", frameon=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    out = out_dir / "wakeup.png"
    fig.savefig(out, dpi=110)
    plt.close(fig)
    shutil.copyfile(out, SITE_IMAGES / "wakeup.png")
    print(f"wrote {out}")


def main() -> None:
    """Render one figure per mode, then the wake-ups."""
    out_dir = HERE / "plots"
    out_dir.mkdir(exist_ok=True)
    wakeups(out_dir)
    count_wakeups()
    for mode, title in MODES:
        fig = plt.figure(figsize=(11, 7))
        ax_t = fig.add_subplot(2, 1, 1)
        ax_h = fig.add_subplot(2, 2, 3)
        ax_l = fig.add_subplot(2, 2, 4)
        for name, label in LABELS:
            rows = powered(load(HERE / "captures" / f"{mode}_{name}.csv.xz"))
            ua = np.array([row[1] for row in rows])
            d0 = np.array([row[2] for row in rows]) == 1
            # From power-on, 3 s, one point in ten.
            shown = np.maximum(ua[:300_000:10], 0.1)
            ax_t.plot(np.arange(len(shown)) / 10_000, shown, label=label, linewidth=0.6, alpha=0.75)
            ecdf(ax_h, ua[SKIP:][d0[SKIP:]], label)
            ecdf(ax_l, ua[SKIP:][~d0[SKIP:]], label)
        ax_t.set_yscale("log")
        ax_t.set_xlabel("time since power-on (s)")
        ax_t.set_ylabel("current (µA, log)")
        ax_t.set_title(f"{title}: both captures from power-on")
        ax_t.legend(loc="upper right")
        ax_h.set_title("distribution of the current, D0 high")
        ax_l.set_title("distribution of the current, D0 low")
        ax_h.set_xlim(0, 3000)
        ax_l.set_xscale("log")
        for ax in (ax_h, ax_l):
            ax.set_xlabel("current (µA)")
            ax.legend(loc="lower right")
            ax.grid(True, alpha=0.3)
        fig.tight_layout()
        out = out_dir / f"{mode}_parity.png"
        fig.savefig(out, dpi=110)
        plt.close(fig)
        shutil.copyfile(out, SITE_IMAGES / f"parity_{mode}.png")
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
