"""HIL tests for the `ppk2` CLI binary: end-to-end through subprocess.

Marked ``@pytest.mark.hardware`` so they skip on the fast tier.

Bench expected: a single PPK2 wired to a DUT running the reference
bench firmware (``bench-dut/``, next to this file), which toggles D0 at 5 Hz and
D1 at 0.5 Hz. Ampere meter mode by default; set ``PPK2_HIL_SOURCE_MV``
(e.g. ``3300``) for Source meter mode, when the PPK2 powers the DUT.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.hardware

_PPK2 = [sys.executable, "-m", "ppk2"]
_SOURCE_MV = os.environ.get("PPK2_HIL_SOURCE_MV")
_MODE = ["--source", "--vdd", str(int(_SOURCE_MV) / 1000)] if _SOURCE_MV else []


def test_cli_capture_emits_byte_format_identical_csv(tmp_path: Path) -> None:
    """Run ``ppk2 capture`` for 2 s, then parse the CSV and check schema invariants."""
    out = tmp_path / "cap.csv"
    result = subprocess.run(
        [*_PPK2, "capture", *_MODE, "--out", str(out), "--seconds", "2"], check=False
    )
    assert result.returncode == 0, f"ppk2 capture failed: {result.returncode}"

    lines = out.read_text().splitlines()
    assert lines[0] == ("Timestamp(ms),Current(uA),D0-D7,D0,D1,D2,D3,D4,D5,D6,D7"), (
        "CSV header drifted from the app's export format"
    )

    # 100 kSPS for 2 s is 200 000 rows. power_on catches up with the
    # stream first, so the count is within 2 %
    # (docs/measure/protocol.md, Known caveats).
    n_rows = len(lines) - 1
    assert 196_000 <= n_rows <= 204_000, f"unexpected row count: {n_rows}"

    # Spot-check a non-header row: 11 comma-separated columns, D0-D7 string
    # is 8 chars wide, last 8 columns are 0 or 1.
    cols = lines[100].split(",")
    assert len(cols) == 11
    assert len(cols[2]) == 8
    for c in cols[3:]:
        assert c in {"0", "1"}


def test_cli_capture_logic_bits_track_d0_d7_string(tmp_path: Path) -> None:
    """The 8-char D0-D7 string must match the per-pin columns row by row."""
    out = tmp_path / "cap.csv"
    subprocess.run([*_PPK2, "capture", *_MODE, "--out", str(out), "--seconds", "1"], check=True)
    lines = out.read_text().splitlines()[1:]
    for raw in lines[:5000]:  # sample the first 5 000 rows; 1 s @ 100 kSPS = 100 000 rows total
        cols = raw.split(",")
        bits_from_string = list(cols[2])
        bits_from_pin_cols = cols[3:]
        assert bits_from_string == bits_from_pin_cols, (
            f"D0-D7 string {cols[2]!r} doesn't match per-pin cols {bits_from_pin_cols!r}"
        )


def test_cli_run_propagates_child_exit_code(tmp_path: Path) -> None:
    """`ppk2 run -- false` must exit non-zero (child's exit code forwarded)."""
    out = tmp_path / "run.csv"
    result = subprocess.run(
        [*_PPK2, "run", *_MODE, "--out", str(out), "--", "false"],
        check=False,
    )
    assert result.returncode != 0, "ppk2 run swallowed the child's non-zero exit"


def test_back_to_back_sessions_dont_wedge(tmp_path: Path) -> None:
    """Two sequential captures must both succeed: the macOS USB CDC wedge recovery."""
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    capture = [*_PPK2, "capture", *_MODE, "--seconds", "1", "--out"]
    r1 = subprocess.run([*capture, str(first)], check=False)
    assert r1.returncode == 0
    # Immediately re-open a session: this is the wedge path.
    r2 = subprocess.run([*capture, str(second)], check=False)
    assert r2.returncode == 0
    assert first.stat().st_size > 0
    assert second.stat().st_size > 0
