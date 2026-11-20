"""``.ppk2`` writer tests: the layout Nordic's Power Profiler app documents."""

import json
import struct
import zipfile
from math import isnan, nan
from pathlib import Path
from typing import Any

import pytest

from ppk2.cli.ppk2file import Ppk2FileWriter


def frames(path: Path) -> list[tuple[float, int]]:
    """Decode ``session.raw`` as ``(current µA, bit pairs)`` per sample."""
    with zipfile.ZipFile(path) as zf:
        raw = zf.read("session.raw")
    assert len(raw) % 6 == 0
    return [
        (struct.unpack_from("<f", raw, off)[0], struct.unpack_from(">H", raw, off + 4)[0])
        for off in range(0, len(raw), 6)
    ]


def member_json(path: Path, name: str) -> Any:
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read(name))


def test_archive_holds_the_three_files(tmp_path: Path) -> None:
    out = tmp_path / "t.ppk2"
    with Ppk2FileWriter(out) as writer:
        writer.add(1.5, 0)

    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == ["metadata.json", "minimap.raw", "session.raw"]
    assert member_json(out, "metadata.json") == {
        "metadata": {"samplesPerSecond": 100_000},
        "formatVersion": 2,
    }
    assert list(tmp_path.iterdir()) == [out], "scratch file left behind"


def test_frame_is_float32_le_then_big_endian_bit_pairs(tmp_path: Path) -> None:
    """Bit pairs: 01 low, 10 high, D0 in the lowest pair (the app's convertBits16)."""
    out = tmp_path / "t.ppk2"
    with Ppk2FileWriter(out) as writer:
        writer.add(12.5, 0b0000_0000)
        writer.add(12.5, 0b1111_1111)
        writer.add(12.5, 0b0000_0001)  # D0 high
        writer.add(12.5, 0b1000_0000)  # D7 high

    assert frames(out) == [(12.5, 0x5555), (12.5, 0xAAAA), (12.5, 0x5556), (12.5, 0x9555)]


def test_below_the_floor_reads_zero_and_lost_samples_stay_nan(tmp_path: Path) -> None:
    out = tmp_path / "t.ppk2"
    with Ppk2FileWriter(out) as writer:
        for current in (0.19, -3.0, 0.2, nan):
            writer.add(current, 0)

    currents = [current for current, _ in frames(out)]
    assert currents[:2] == [0.0, 0.0]
    assert currents[2] == pytest.approx(0.2)  # pyright: ignore[reportUnknownMemberType]
    assert isnan(currents[3])
    assert writer.count == 4


def test_minimap_envelopes_the_whole_trace(tmp_path: Path) -> None:
    out = tmp_path / "t.ppk2"
    n = 25_000
    with Ppk2FileWriter(out) as writer:
        for i in range(n):
            writer.add(1.0 + i % 100, 0)  # 1..100 µA

    minimap = member_json(out, "minimap.raw")
    lo, hi = minimap["data"]["min"], minimap["data"]["max"]
    assert minimap["data"]["length"] == len(lo) == len(hi)
    assert len(lo) <= minimap["maxNumberOfElements"] == 10_000
    assert minimap["numberOfTimesToFold"] == 4  # folded twice on the way to 25 000
    assert min(p["y"] for p in lo) == 1_000.0  # nA
    assert max(p["y"] for p in hi) == 100_000.0
    assert all(a["y"] <= b["y"] for a, b in zip(lo, hi, strict=True))
    times = [p["x"] for p in lo]
    assert times == sorted(times)
    assert times[0] >= 0.0
    assert times[-1] <= (n - 1) * 10.0  # µs at 100 kSPS


def test_minimap_floors_at_200_na_and_skips_lost_samples(tmp_path: Path) -> None:
    out = tmp_path / "t.ppk2"
    with Ppk2FileWriter(out) as writer:
        writer.add(0.0, 0)
        writer.add(nan, 0)

    data = member_json(out, "minimap.raw")["data"]
    assert [p["y"] for p in data["min"]] == [200.0, 1.7976931348623157e308]
    assert [p["y"] for p in data["max"]] == [200.0, -1.7976931348623157e308]


def test_file_is_written_even_when_the_block_raises(tmp_path: Path) -> None:
    out = tmp_path / "t.ppk2"
    with pytest.raises(RuntimeError), Ppk2FileWriter(out) as writer:
        writer.add(7.0, 0)
        raise RuntimeError("capture interrupted")

    assert frames(out) == [(7.0, 0x5555)]


def test_rejects_a_rate_the_app_cannot_replay(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sample rate"):
        Ppk2FileWriter(tmp_path / "t.ppk2", 44_100)
    assert list(tmp_path.iterdir()) == []


def test_no_file_for_a_capture_with_no_sample(tmp_path: Path) -> None:
    """An empty capture leaves an earlier file of the same name alone."""
    out = tmp_path / "t.ppk2"
    with Ppk2FileWriter(out) as w:
        w.add(42.0, 0)
    earlier = out.read_bytes()

    with Ppk2FileWriter(out):
        pass

    assert out.read_bytes() == earlier
    assert sorted(p.name for p in tmp_path.iterdir()) == ["t.ppk2"]


def test_a_failed_write_keeps_the_frames_and_the_earlier_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file is replaced only by a complete one; the samples are not lost."""
    out = tmp_path / "t.ppk2"
    with Ppk2FileWriter(out) as w:
        w.add(1.0, 0)
    earlier = out.read_bytes()

    def no_room(*_args: object, **_kwargs: object) -> None:
        raise OSError(28, "No space left on device")

    writer = Ppk2FileWriter(out)
    writer.add(2.0, 0)
    writer.add(3.0, 0)
    monkeypatch.setattr(zipfile.ZipFile, "write", no_room)
    with pytest.raises(OSError, match="No space left"):
        writer.close()

    assert out.read_bytes() == earlier
    assert (tmp_path / "t.ppk2.frames").stat().st_size == 2 * 6
    assert not (tmp_path / "t.ppk2.part").exists()


def test_discard_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "t.ppk2"
    writer = Ppk2FileWriter(out)
    writer.add(1.0, 0)

    writer.discard()

    assert list(tmp_path.iterdir()) == []
