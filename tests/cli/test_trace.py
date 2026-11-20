"""``TraceFile`` tests: one writer for ``capture`` and ``run``."""

from math import nan
from pathlib import Path

from ppk2.cli.csv import CSV_HEADER, fmt_ts
from ppk2.cli.trace import TraceFile
from tests.cli.test_ppk2file import frames


def test_csv_rows_are_stamped_from_the_sample_index(tmp_path: Path) -> None:
    out = tmp_path / "t.csv"
    with TraceFile(out) as trace:
        trace.add(1.0, 0b01)
        trace.add(nan, 0)  # a lost sample: no row, the next timestamp skips its slot
        trace.add(2.0, 0b10)

    assert out.read_text().splitlines() == [
        CSV_HEADER,
        "0,1.000,10000000,1,0,0,0,0,0,0,0",
        "0.02,2.000,01000000,0,1,0,0,0,0,0,0",
    ]


def test_a_timestamp_forty_minutes_in_is_exact() -> None:
    """A running sum of 0.01 has drifted to 2409999.99 by this sample."""
    assert fmt_ts(241_000_000 * 0.01) == "2410000"


def test_a_ppk2_name_in_any_case_gets_a_session_file(tmp_path: Path) -> None:
    out = tmp_path / "T.PPK2"
    with TraceFile(out) as trace:
        trace.add(5.0, 0)
        trace.add(nan, 0)

    assert trace.is_ppk2
    assert len(frames(out)) == 2
