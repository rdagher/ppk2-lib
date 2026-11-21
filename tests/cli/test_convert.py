"""``ppk2 convert`` tests: CSV rows in, ``.ppk2`` frames out."""

import gzip
import json
import zipfile
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from ppk2.cli.commands.convert import convert
from ppk2.cli.csv import CSV_HEADER, write_csv_row
from ppk2.cli.main import app
from tests.cli.test_ppk2file import frames

Row = tuple[float, float, int]  # timestamp ms, current µA, logic byte


def write_csv(path: Path, rows: list[Row]) -> None:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as out:
        out.write(f"{CSV_HEADER}\n")
        for t_ms, current, logic in rows:
            write_csv_row(out, t_ms, current, logic)


def sample_rate(path: Path) -> int:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("metadata.json"))["metadata"]["samplesPerSecond"]


def test_rows_become_frames(tmp_path: Path) -> None:
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    write_csv(src, [(0.0, 12.5, 0b0000_0001), (0.01, 250.0, 0b0000_0011), (0.02, 0.0, 0)])

    convert(src, dst)

    assert frames(dst) == [(12.5, 0x5556), (250.0, 0x555A), (0.0, 0x5555)]
    assert sample_rate(dst) == 100_000


def test_a_jump_in_timestamps_is_filled_with_0_2_ua(tmp_path: Path) -> None:
    """Lost samples have no CSV row; the trace after them must not slide earlier."""
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    write_csv(src, [(0.0, 1.0, 0), (0.01, 2.0, 0), (0.05, 3.0, 0)])  # 0.02-0.04 lost

    convert(src, dst)

    currents = [current for current, _ in frames(dst)]
    assert currents[:2] == [1.0, 2.0]
    assert all(abs(c - 0.2) < 1e-6 for c in currents[2:5])  # float32
    assert currents[5] == 3.0


def test_rate_comes_from_the_timestamp_step(tmp_path: Path) -> None:
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    write_csv(src, [(5.0, 1.0, 0), (5.1, 2.0, 0), (5.2, 3.0, 0)])  # 10 kSPS, window from 5 ms

    convert(src, dst)

    assert sample_rate(dst) == 10_000
    assert len(frames(dst)) == 3


def test_reads_gzipped_captures(tmp_path: Path) -> None:
    src, dst = tmp_path / "t.csv.gz", tmp_path / "t.ppk2"
    write_csv(src, [(0.0, 4.0, 0), (0.01, 5.0, 0)])

    convert(src, dst)

    assert [current for current, _ in frames(dst)] == [4.0, 5.0]


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("Current(uA),D0-D7\n1.0,00000000\n", "needs the Timestamp(ms) and Current(uA) columns"),
        (f"{CSV_HEADER}\n", "no samples"),
        (f"{CSV_HEADER}\n0,1.0,00000000\n0.03,1.0,00000000\n", "not a rate the app supports"),
        (f"{CSV_HEADER}\n0,1.0,00000000\n0.01,oops,00000000\n", "malformed row at line 3"),
        (f"{CSV_HEADER}\n0,1.0,00000000\n0.01,1.0,0\n2000,1.0,0\n", "jump by over a second"),
    ],
)
def test_bad_input_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, complaint: str
) -> None:
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    src.write_text(text, encoding="utf-8")

    with pytest.raises(typer.Exit) as exc:
        convert(src, dst)

    assert exc.value.exit_code == 1
    assert complaint in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["t.csv"], "partial output left behind"


def test_cli_command(tmp_path: Path) -> None:
    src, dst = tmp_path / "t.csv", tmp_path / "out" / "t.ppk2"
    write_csv(src, [(0.0, 1.0, 0), (0.01, 2.0, 0)])

    result = CliRunner().invoke(app, ["convert", str(src), str(dst)])

    assert result.exit_code == 0, result.output
    assert len(frames(dst)) == 2


def test_rate_survives_a_lost_sample_between_the_first_rows(tmp_path: Path) -> None:
    """The step is the smallest one among the first rows, not the first one."""
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    write_csv(src, [(0.0, 1.0, 0), (0.02, 2.0, 0), (0.03, 3.0, 0)])  # 0.01 lost

    convert(src, dst)

    assert sample_rate(dst) == 100_000
    currents = [current for current, _ in frames(dst)]
    assert currents[0] == 1.0
    assert abs(currents[1] - 0.2) < 1e-6  # a float32
    assert currents[2:] == [2.0, 3.0]


def test_timestamps_that_go_back_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    write_csv(src, [(0.0, 1.0, 0), (0.01, 2.0, 0), (0.01, 3.0, 0)])

    with pytest.raises(typer.Exit):
        convert(src, dst)

    assert "timestamps go back at line 4" in capsys.readouterr().err
    assert list(tmp_path.glob("t.ppk2*")) == []


def test_a_failed_conversion_keeps_an_earlier_file(tmp_path: Path) -> None:
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    write_csv(src, [(0.0, 1.0, 0), (0.01, 2.0, 0)])
    convert(src, dst)
    earlier = dst.read_bytes()
    src.write_text(f"{CSV_HEADER}\n0,1.0,0\n0.01,not-a-number,0\n")

    with pytest.raises(typer.Exit):
        convert(src, dst)

    assert dst.read_bytes() == earlier
    assert sorted(p.name for p in tmp_path.iterdir()) == ["t.csv", "t.ppk2"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "No such file"),
        (b"\xff\xfe\x00garbage", "not a text file"),
        (f"{CSV_HEADER}\n0,1e39,00000000\n".encode(), "current out of range at line 2"),
    ],
)
def test_input_errors_are_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes | None, message: str
) -> None:
    src, dst = tmp_path / "t.csv", tmp_path / "t.ppk2"
    if content is not None:
        src.write_bytes(content)

    with pytest.raises(typer.Exit):
        convert(src, dst)

    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert message in err
    assert err.count("\n") == 1
    assert not dst.exists()
