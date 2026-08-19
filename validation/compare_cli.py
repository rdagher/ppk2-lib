"""Cross-validate two GUI-parity CSVs and emit a Markdown report.

Port-agnostic: feed it any two CSVs produced by a ppk2-compatible
capture binary (this repo's ``ppk2``, any other ppk2-compatible CLI, or
the Nordic Power Profiler GUI's CSV export). The comparison reports
schema, sample rate, current statistics, KS test, per-pin duty and
edge rates.

Usage:
    uv run --group validation python -m validation.compare_cli A.csv B.csv
        [--label-a NAME] [--label-b NAME] [--out report.md]

Acceptance contract:
    - Headers byte-identical
    - Mean current Δ within ±1 %
    - KS statistic < 0.05
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from scipy import stats

LOGIC_COLS = ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"]


def load_csv(path: Path) -> pd.DataFrame:
    """Read a GUI-parity CSV with the D0-D7 column kept as a string."""
    return pd.read_csv(path, dtype={"D0-D7": str})


def _stats(df: pd.DataFrame) -> dict[str, float | int | bool]:
    """Compute the headline metrics for one capture."""
    duration_s = float(df["Timestamp(ms)"].iloc[-1]) / 1000.0
    out: dict[str, float | int | bool] = {
        "rows": len(df),
        "duration_s": duration_s,
        "rate_hz": (len(df) - 1) / duration_s if duration_s > 0 else 0.0,
        "mean_uA": float(df["Current(uA)"].mean()),
        "max_uA": float(df["Current(uA)"].max()),
        "min_uA": float(df["Current(uA)"].min()),
        "std_uA": float(df["Current(uA)"].std()),
    }
    for col in LOGIC_COLS:
        out[f"{col}_duty_pct"] = 100.0 * float((df[col] == 1).mean())
        rising = int((df[col].diff() == 1).sum())
        out[f"{col}_rising_edges"] = rising
        out[f"{col}_rising_per_s"] = rising / duration_s if duration_s > 0 else 0.0
    return out


def _pct_delta(a: float, b: float) -> float:
    """Percent change of ``a`` vs ``b`` (positive = a is greater)."""
    if b == 0:
        return float("nan") if a == 0 else float("inf")
    return 100.0 * (a - b) / b


def _ks(a: pd.Series, b: pd.Series) -> tuple[float, float]:
    """Two-sample KS statistic + p-value on the current columns (subsampled)."""
    # 100 kSPS for 30+ s is millions of rows; KS doesn't need that many.
    # Subsample to 100 k each for a fast, representative test.
    n = min(100_000, len(a), len(b))
    sa = a.sample(n=n, random_state=42, replace=False)
    sb = b.sample(n=n, random_state=42, replace=False)
    result = stats.ks_2samp(sa, sb)
    return float(result.statistic), float(result.pvalue)


def build_report(
    a_path: Path,
    b_path: Path,
    a_label: str,
    b_label: str,
    a: pd.DataFrame,
    b: pd.DataFrame,
    *,
    skip_initial_s: float = 0.0,
    mean_tolerance_pct: float = 1.0,
) -> str:
    """Build a Markdown report comparing capture A against capture B.

    Args:
        a_path: Path of the first CSV (report provenance line).
        b_path: Path of the second CSV.
        a_label: Display label for the first capture.
        b_label: Display label for the second capture.
        a: First capture, loaded via [`load_csv`][validation.compare_cli.load_csv].
        b: Second capture.
        skip_initial_s: Trim this many leading seconds from BOTH
            captures before computing statistics. Use ~2 s for
            captures taken with boot-inclusive semantics (t=0 at
            FET-on): the DUT's boot inrush is a per-power-cycle
            physical event that legitimately differs between two
            sequential captures, so including it makes the mean gate
            measure boot variance, not implementation agreement.
        mean_tolerance_pct: Acceptance threshold for the mean-current
            delta. The 1.0 default was calibrated on an active-burst
            workload (~38 µA mean dominated by deterministic bursts).
            For idle-level DUTs (tens of µA), same-binary replicate
            runs on the reference bench (see ``firmware/bench-dut/``)
            differ by ~2-3 % — set the tolerance from a replicate
            pair, or treat the mean as informational and gate on
            headers + KS + duty/edges.
    """
    if skip_initial_s > 0:
        cutoff_ms = skip_initial_s * 1000.0
        a = a[a["Timestamp(ms)"] >= cutoff_ms]
        b = b[b["Timestamp(ms)"] >= cutoff_ms]
    a_s = _stats(a)
    b_s = _stats(b)

    headers_match = list(a.columns) == list(b.columns)
    mean_delta = _pct_delta(a_s["mean_uA"], b_s["mean_uA"])
    ks_stat, ks_p = _ks(a["Current(uA)"], b["Current(uA)"])

    trim_note = f" (first {skip_initial_s:g} s trimmed from both)" if skip_initial_s > 0 else ""
    lines = [
        f"# Cross-validation — {a_label} vs {b_label}{trim_note}",
        "",
        f"- **{a_label}:** `{a_path}` — {a_s['rows']:,} rows, {a_s['duration_s']:.2f} s",
        f"- **{b_label}:** `{b_path}` — {b_s['rows']:,} rows, {b_s['duration_s']:.2f} s",
        "",
        "## Schema",
        "",
        f"Headers byte-identical: **{headers_match}**",
        "",
        "## Sample rate",
        "",
        "| Capture | Rate (Hz) | Δ vs nominal |",
        "|---|---:|---:|",
        f"| {a_label} | {a_s['rate_hz']:,.1f} | {a_s['rate_hz'] / 1000 - 100:+.4f} kHz |",
        f"| {b_label} | {b_s['rate_hz']:,.1f} | {b_s['rate_hz'] / 1000 - 100:+.4f} kHz |",
        "",
        "## Current statistics",
        "",
        f"| Statistic | {a_label} | {b_label} | Δ |",
        "|---|---:|---:|---:|",
        f"| Mean (µA) | {a_s['mean_uA']:.3f} | {b_s['mean_uA']:.3f} | **{mean_delta:+.2f} %** |",
        f"| Std  (µA) | {a_s['std_uA']:.3f} | {b_s['std_uA']:.3f} | "
        f"{_pct_delta(a_s['std_uA'], b_s['std_uA']):+.2f} % |",
        f"| Max  (µA) | {a_s['max_uA']:.3f} | {b_s['max_uA']:.3f} | "
        f"{_pct_delta(a_s['max_uA'], b_s['max_uA']):+.2f} % |",
        f"| Min  (µA) | {a_s['min_uA']:.3f} | {b_s['min_uA']:.3f} | — |",
        "",
        "## Distributional comparison (Kolmogorov-Smirnov)",
        "",
        "Two-sample KS on 100 k subsampled rows from each capture:",
        "",
        f"- **KS statistic:** {ks_stat:.4f}",
        f"- **p-value:** {ks_p:.4f}",
        "",
        "## Logic pins (rate-based, duration-independent)",
        "",
        f"| Pin | {a_label} duty (%) | {b_label} duty (%) | "
        f"{a_label} edges/s | {b_label} edges/s |",
        "|---|---:|---:|---:|---:|",
    ]
    for col in LOGIC_COLS:
        lines.append(
            f"| {col} | "
            f"{a_s[f'{col}_duty_pct']:7.4f} | {b_s[f'{col}_duty_pct']:7.4f} | "
            f"{a_s[f'{col}_rising_per_s']:6.3f} | "
            f"{b_s[f'{col}_rising_per_s']:6.3f} |"
        )
    lines += [
        "",
        "## Acceptance contract",
        "",
        f"- Headers byte-identical: **{'pass' if headers_match else 'FAIL'}**",
        f"- Mean-current Δ within ±{mean_tolerance_pct:g} %: "
        f"**{'pass' if abs(mean_delta) <= mean_tolerance_pct else 'FAIL'}** "
        f"({mean_delta:+.2f} %)",
        f"- KS statistic < 0.05: **{'pass' if ks_stat < 0.05 else 'FAIL'}** ({ks_stat:.4f})",
        "",
    ]
    return "\n".join(lines)


def verdict_from_report(report: str) -> int:
    """Return 0 if every acceptance line says 'pass', else 1."""
    return 0 if "FAIL" not in report else 1


def main() -> int:
    """Parse CLI args, build the report, write to stdout or --out."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("a", type=Path, help="First CSV (label A by default)")
    ap.add_argument("b", type=Path, help="Second CSV (label B by default)")
    ap.add_argument("--label-a", default="A", help="Display label for the first CSV")
    ap.add_argument("--label-b", default="B", help="Display label for the second CSV")
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write Markdown report to this path (default: stdout).",
    )
    ap.add_argument(
        "--skip-initial-s",
        type=float,
        default=0.0,
        help=(
            "Trim this many leading seconds from both captures before "
            "computing statistics (use ~2 for boot-inclusive captures: the "
            "boot inrush is a per-power-cycle event, not an implementation "
            "property)."
        ),
    )
    ap.add_argument(
        "--mean-tolerance-pct",
        type=float,
        default=1.0,
        help=(
            "Acceptance threshold for the mean-current delta. The 1.0 "
            "default suits active-burst workloads; idle-level DUTs show "
            "2-3 %% same-binary replicate spread on the reference bench "
            "(see ``firmware/bench-dut/``) — calibrate from a replicate "
            "pair."
        ),
    )
    args = ap.parse_args()

    a = load_csv(args.a)
    b = load_csv(args.b)
    report = build_report(
        args.a,
        args.b,
        args.label_a,
        args.label_b,
        a,
        b,
        skip_initial_s=args.skip_initial_s,
        mean_tolerance_pct=args.mean_tolerance_pct,
    )

    if args.out:
        args.out.write_text(report)
        sys.stderr.write(f"compare_cli: wrote report to {args.out}\n")
    else:
        sys.stdout.write(report)

    return verdict_from_report(report)


if __name__ == "__main__":
    raise SystemExit(main())
