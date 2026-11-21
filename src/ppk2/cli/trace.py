"""The file ``capture`` and ``run`` write their samples to."""

from math import isnan
from pathlib import Path
from typing import TextIO

from ppk2.cli.csv import CSV_HEADER, write_csv_row
from ppk2.cli.ppk2file import Ppk2FileWriter

SAMPLE_RATE_HZ = 100_000

#: What a lost sample is recorded as, in µA, with its digital inputs low.
#: Nordic's app does this (``value ?? 0.2`` in its ``onSample``), so a
#: file written here and one saved by the app treat a loss alike. It is
#: a made-up reading: it pulls sums and means towards 0.2 µA in
#: proportion to the loss. The library itself reports a lost sample as
#: NaN, and a capture counts them.
LOST_SAMPLE_UA = 0.2
_SAMPLE_PERIOD_MS = 1000.0 / SAMPLE_RATE_HZ  # 0.01


class TraceFile:
    """A capture on disk: a ``.ppk2`` session file, or the 11-column CSV.

    The name decides: ``.ppk2``, in any case, or anything else for CSV.
    A lost sample (NaN) keeps its place in time and is recorded as
    ``LOST_SAMPLE_UA`` with its digital inputs low, as Nordic's app
    records it.
    """

    def __init__(self, path: Path) -> None:
        self.is_ppk2 = path.suffix.lower() == ".ppk2"
        self._ppk2 = Ppk2FileWriter(path) if self.is_ppk2 else None
        self._csv: TextIO | None = None
        if self._ppk2 is None:
            self._csv = path.open("w", encoding="utf-8")
            self._csv.write(f"{CSV_HEADER}\n")
        self._slot = 0

    def __enter__(self) -> "TraceFile":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def add(self, current_ua: float, logic: int) -> None:
        """Append one sample; NaN marks a lost one."""
        if isnan(current_ua):
            current_ua, logic = LOST_SAMPLE_UA, 0
        if self._ppk2 is not None:
            self._ppk2.add(current_ua, logic)
        elif self._csv is not None:
            # From the sample index: a running sum of 0.01 drifts and,
            # after some 40 minutes, repeats a timestamp.
            write_csv_row(self._csv, self._slot * _SAMPLE_PERIOD_MS, current_ua, logic)
        self._slot += 1

    def close(self) -> None:
        """Complete the file. Safe to call twice."""
        if self._ppk2 is not None:
            self._ppk2.close()
        if self._csv is not None and not self._csv.closed:
            self._csv.close()
