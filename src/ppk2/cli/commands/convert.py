"""``ppk2 convert``: rewrite a CSV capture as a ``.ppk2`` session file."""

import gzip
import struct
import sys
from itertools import chain, islice, pairwise
from math import nan
from pathlib import Path
from typing import NoReturn, TextIO

import typer

from ppk2.cli.ppk2file import SAMPLE_RATES, Ppk2FileWriter

# Rows read ahead to find the sample period: enough to hold two
# neighbouring samples even where some were lost.
_ROWS_FOR_RATE = 64


def convert(src: Path, dst: Path) -> None:
    """Rewrite the CSV capture ``src`` (plain or ``.gz``) as the ``.ppk2`` file ``dst``.

    The sample rate is the smallest step between the first timestamps.
    A CSV has no row for a lost sample, only a jump in its timestamps,
    and a ``.ppk2`` has no timestamps at all: each jump is filled with
    NaN frames so the rest of the trace stays where it was in time.

    On any error nothing is written, and an existing ``dst`` is kept.
    """
    try:
        count, rate, lost = _convert(src, dst)
    except UnicodeDecodeError:
        _fail(f"{src}: not a text file")
    except EOFError:
        _fail(f"{src}: the compressed file is cut short")
    except OSError as exc:
        _fail(f"{exc.filename or src}: {exc.strerror or exc}")

    note = ""
    if lost:
        note = (
            ", 1 lost sample kept as a gap" if lost == 1 else f", {lost} lost samples kept as gaps"
        )
    sys.stderr.write(f"wrote {dst}: {count} samples at {rate} S/s ({count / rate:.2f} s){note}\n")


def _convert(src: Path, dst: Path) -> tuple[int, int, int]:
    """Do the conversion; return (samples written, rate, lost samples among them)."""
    with _open_text(src) as rows:
        columns = rows.readline().strip().split(",")
        if "Timestamp(ms)" not in columns or "Current(uA)" not in columns:
            _fail(f"{src}: needs the Timestamp(ms) and Current(uA) columns")
        i_time = columns.index("Timestamp(ms)")
        i_current = columns.index("Current(uA)")
        i_logic = columns.index("D0-D7") if "D0-D7" in columns else None

        head = list(islice(rows, _ROWS_FOR_RATE))
        try:
            times = [float(line.split(",")[i_time]) for line in head if line.strip()]
        except (ValueError, IndexError):
            _fail(f"{src}: cannot read the timestamps of the first rows")
        if not times:
            _fail(f"{src}: no samples")
        step_ms = min((b - a for a, b in pairwise(times) if b > a), default=0.01)
        rate = round(1000.0 / step_ms)
        if rate not in SAMPLE_RATES:
            _fail(f"{src}: {step_ms:g} ms between samples is not a rate the app supports")
        t0 = times[0]

        dst.parent.mkdir(parents=True, exist_ok=True)
        logic_of: dict[str, int] = {}  # "10000000" (D0 leftmost) -> 0x01
        lost = 0
        out = Ppk2FileWriter(dst, rate)
        try:
            for row, line in enumerate(chain(head, rows), start=2):
                if not line.strip():
                    continue
                fields = line.split(",")
                try:
                    slot = round((float(fields[i_time]) - t0) * rate / 1000.0)
                    current = float(fields[i_current])
                    logic = 0
                    if i_logic is not None:
                        bits = fields[i_logic].strip()
                        logic = logic_of.get(bits, -1)
                        if logic < 0:
                            logic = logic_of[bits] = int(bits[::-1], 2)
                except (ValueError, IndexError):
                    _fail(f"{src}: malformed row at line {row}")
                if slot < out.count:
                    _fail(f"{src}: timestamps go back at line {row}")
                if slot - out.count > rate:
                    _fail(f"{src}: timestamps jump by over a second at line {row}")
                for _ in range(slot - out.count):
                    out.add(nan, 0)
                    lost += 1
                try:
                    out.add(current, logic)
                except (OverflowError, struct.error):
                    _fail(f"{src}: current out of range at line {row}")
        except BaseException:
            out.discard()
            raise
        out.close()
    return out.count, rate, lost


def _open_text(path: Path) -> TextIO:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def _fail(message: str) -> NoReturn:
    sys.stderr.write(f"error: {message}\n")
    raise typer.Exit(code=1)
