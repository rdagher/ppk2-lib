r"""Capture from any two ppk2-compatible binaries back-to-back, then compare.

Port-agnostic harness. Invokes ``$BIN_A capture`` and ``$BIN_B capture``
against the bench, then runs the same comparison logic as
:mod:`validation.compare_cli` on the resulting CSVs.

Usage:
    uv run --group validation python -m validation.cross_validate \
        --binary-a BIN_A [--label-a NAME] \
        --binary-b BIN_B [--label-b NAME] \
        [--seconds 60] [--out-dir DIR]

Exits 0 if every acceptance line in the comparison report says "pass",
1 otherwise.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from validation.compare_cli import build_report, load_csv, verdict_from_report


def _capture(binary: list[str], out: Path, seconds: float, label: str) -> None:
    """Run one ``<binary> capture --out OUT --seconds N`` invocation."""
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [*binary, "capture", "--out", str(out), "--seconds", str(seconds)]
    sys.stderr.write(f"\n=== capturing {label} -> {out.name} ({seconds:.0f} s) ===\n")
    sys.stderr.write(f"    {' '.join(cmd)}\n\n")
    subprocess.run(cmd, check=True)


def _slug(label: str) -> str:
    """Return a filesystem-safe slug for ``label``."""
    cleaned = "".join(c if c.isalnum() else "_" for c in label).strip("_")
    return cleaned or "x"


def main() -> int:
    """Capture-then-compare orchestration; return acceptance verdict (0|1)."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary-a", required=True, type=Path, help="Path to the first ppk2 binary.")
    ap.add_argument("--binary-b", required=True, type=Path, help="Path to the second ppk2 binary.")
    ap.add_argument("--label-a", default="A", help="Display label for binary A.")
    ap.add_argument("--label-b", default="B", help="Display label for binary B.")
    ap.add_argument(
        "--seconds",
        type=float,
        default=60.0,
        help="Duration of each capture in seconds (default: 60).",
    )
    ap.add_argument(
        "--skip-initial-s",
        type=float,
        default=0.0,
        help=(
            "Trim this many leading seconds from both captures before "
            "stats (boot-inclusive captures: use ~2)."
        ),
    )
    ap.add_argument(
        "--mean-tolerance-pct",
        type=float,
        default=1.0,
        help=(
            "Mean-current acceptance threshold; calibrate from a "
            "same-binary replicate pair on idle-level DUTs."
        ),
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("validation/evidence/cross_validate"),
        help="Where to write the two captures + the report.",
    )
    args = ap.parse_args()

    for binary in (args.binary_a, args.binary_b):
        if not binary.exists():
            sys.stderr.write(f"cross_validate: binary not found: {binary}\n")
            return 2

    a_csv = args.out_dir / f"{_slug(args.label_a)}_capture.csv"
    b_csv = args.out_dir / f"{_slug(args.label_b)}_capture.csv"
    report_path = args.out_dir / "comparison_report.md"

    try:
        _capture([str(args.binary_a)], a_csv, args.seconds, args.label_a)
        _capture([str(args.binary_b)], b_csv, args.seconds, args.label_b)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"cross_validate: capture failed: {exc}\n")
        return 3

    a = load_csv(a_csv)
    b = load_csv(b_csv)
    report = build_report(
        a_csv,
        b_csv,
        args.label_a,
        args.label_b,
        a,
        b,
        skip_initial_s=args.skip_initial_s,
        mean_tolerance_pct=args.mean_tolerance_pct,
    )
    report_path.write_text(report, encoding="utf-8")
    sys.stderr.write(f"\ncross_validate: wrote report to {report_path}\n")

    verdict = verdict_from_report(report)
    sys.stderr.write(
        "cross_validate: ACCEPTANCE PASS\n"
        if verdict == 0
        else "cross_validate: ACCEPTANCE FAIL: see report\n"
    )
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
