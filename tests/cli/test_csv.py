"""CSV format helper tests.

Cases pulled verbatim from a real export of Nordic's app so any drift
in our formatting surfaces immediately.
"""

from io import StringIO
from math import isnan, nan

from ppk2.cli.csv import (
    CSV_HEADER,
    fmt_logic_d0d7,
    fmt_ts,
    noise_floor,
    vdd_to_mv,
    write_csv_row,
)


def test_noise_floor_matches_device_actions() -> None:
    """deviceActions.ts:333-337: everything below 0.2 µA -> exactly 0."""
    assert noise_floor(-1.32) == 0.0
    assert noise_floor(0.0) == 0.0
    assert noise_floor(0.199) == 0.0
    assert noise_floor(0.2) == 0.2
    assert noise_floor(14.53) == 14.53
    # NaN passes through so the skip-row path still sees it.
    assert isnan(noise_floor(nan))


def test_clamped_row_writes_exact_zero() -> None:
    out = StringIO()
    write_csv_row(out, 0.01, noise_floor(0.084), 0)
    assert out.getvalue() == "0.01,0.000,00000000,0,0,0,0,0,0,0,0\n"


def test_csv_header_matches_gui_export() -> None:
    assert CSV_HEADER == "Timestamp(ms),Current(uA),D0-D7,D0,D1,D2,D3,D4,D5,D6,D7"


def test_fmt_ts_matches_gui_style() -> None:
    """%g-style: drop trailing zeros and the trailing decimal point."""
    assert fmt_ts(0.0) == "0"
    assert fmt_ts(0.01) == "0.01"
    assert fmt_ts(0.09) == "0.09"
    assert fmt_ts(0.10) == "0.1"
    assert fmt_ts(10.0) == "10"
    assert fmt_ts(10.08) == "10.08"
    assert fmt_ts(100.0) == "100"
    assert fmt_ts(1000.0) == "1000"


def test_fmt_logic_d0d7_d0_leftmost() -> None:
    """The app prints D0 as the leftmost character of the 8-char field."""
    assert fmt_logic_d0d7(0b0000_0000) == "00000000"
    assert fmt_logic_d0d7(0b0000_0001) == "10000000"  # D0=1
    assert fmt_logic_d0d7(0b1000_0000) == "00000001"  # D7=1
    assert fmt_logic_d0d7(0b1010_0101) == "10100101"  # D0, D2, D5, D7=1
    assert fmt_logic_d0d7(0xFF) == "11111111"


def test_write_csv_row_matches_the_apps_layout() -> None:
    """Verbatim line from an export of Nordic's app."""
    buf = StringIO()
    write_csv_row(buf, 0.0, 2.846, 0b0000_0001)
    assert buf.getvalue() == "0,2.846,10000000,1,0,0,0,0,0,0,0\n"

    buf = StringIO()
    write_csv_row(buf, 10.08, 3.022, 0)
    assert buf.getvalue() == "10.08,3.022,00000000,0,0,0,0,0,0,0,0\n"


def test_write_csv_row_writes_whatever_it_is_given() -> None:
    """write_csv_row does not filter NaN: that policy lives in the callers.

    Both capture loops skip (and count) data-loss placeholders before
    calling this helper; the loop-level skip is pinned in
    tests/cli/test_capture_semantics.py. The helper itself writes the
    row verbatim, NaN included.
    """
    buf = StringIO()
    write_csv_row(buf, 0.05, nan, 0xFF)
    assert buf.getvalue() == "0.05,nan,11111111,1,1,1,1,1,1,1,1\n"


def test_vdd_to_mv_clamps() -> None:
    """Within range stays; outside clamps to [800, 5000]."""
    assert vdd_to_mv(3.3) == 3300
    assert vdd_to_mv(0.5) == 800
    assert vdd_to_mv(6.0) == 5000
    assert vdd_to_mv(0.8) == 800  # boundary
    assert vdd_to_mv(5.0) == 5000  # boundary
