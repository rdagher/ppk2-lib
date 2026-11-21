"""Capture end-block semantics: Session stubbed, no hardware.

Pins: n == 0 -> exit 1 with the mode/power diagnostic; sub-95 % realized
rate -> the dropped-samples watchdog; Ctrl-C -> "interrupted: CSV
flushed" + exit 130 with the partial CSV intact; lost samples count
toward the stream rate and are rows of 0.2 µA.
"""

import signal
from collections.abc import Callable
from math import nan
from pathlib import Path
from time import sleep

import pytest

from ppk2 import Sample
from ppk2.cli.commands import capture as capture_module
from ppk2.cli.csv import CSV_HEADER
from ppk2.cli.main import dispatch
from tests.cli.test_ppk2file import frames

_REAL = Sample(current_micro_amps=12.5, logic=0x03)
_NAN = Sample(current_micro_amps=nan, logic=0)


class _FakeSession:
    """Stands in for ppk2.Session inside the capture command.

    ``interrupt`` delivers a real SIGINT mid-capture (handled by the
    command's ``_SigintFlag``), emitting one row before and attempting
    one after: like a user's Ctrl-C between samples.
    """

    def __init__(
        self,
        samples: list[Sample],
        wall_s: float = 0.0,
        *,
        interrupt: bool = False,
    ) -> None:
        self._samples = samples
        self._wall_s = wall_s
        self._interrupt = interrupt

    # -- lifecycle no-ops --------------------------------------------------
    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def set_mode(self, _mode: object) -> None:
        return None

    def set_source_voltage(self, _mv: int) -> None:
        return None

    def set_user_gain(self, _range_idx: int, _gain: float) -> None:
        return None

    def start_measuring(self) -> None:
        return None

    def power_on(self) -> None:
        return None

    def power_off(self) -> None:
        return None

    def stop_measuring(self) -> None:
        return None

    def drop_pending_backlog(self) -> int:
        return 0

    # -- the loop ----------------------------------------------------------
    def capture(
        self,
        emit: Callable[[Sample], bool],
        on_dataloss: Callable[[int], None] | None = None,
    ) -> None:
        del on_dataloss
        if self._interrupt:
            emit(_REAL)  # one row lands before the interrupt
            signal.raise_signal(signal.SIGINT)  # handled by capture's _SigintFlag
            emit(_REAL)  # flag now set -> emit returns False -> loop stops
            return
        if self._wall_s:
            sleep(self._wall_s)
        for sample in self._samples:
            if not emit(sample):
                return


class _Opener:
    """Duck-types the ``Session.open`` classmethod surface."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def open(self, _device: str) -> _FakeSession:
        return self._session


def _fake_resolve(_serial: str | None, _port: str | None) -> str:
    return "/dev/fake"


def _install(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    monkeypatch.setattr(capture_module, "resolve_device", _fake_resolve)
    monkeypatch.setattr(capture_module, "Session", _Opener(session))


def test_zero_samples_exits_1_with_mode_power_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install(monkeypatch, _FakeSession(samples=[]))
    out = tmp_path / "empty.csv"
    code = dispatch(["capture", "-o", str(out), "-s", "0.1"])
    captured = capsys.readouterr()
    assert code == 1
    assert "error: no samples captured: check the PPK2 mode and the DUT's power" in captured.err
    assert out.read_text().splitlines() == [CSV_HEADER]


def test_low_realized_rate_prints_dropped_samples_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """0.6 s wall with a handful of samples ≪ 95 % of 100 kSPS -> WARNING."""
    _install(monkeypatch, _FakeSession(samples=[_REAL], wall_s=0.6))
    code = dispatch(["capture", "-o", str(tmp_path / "slow.csv"), "-s", "0.1"])
    captured = capsys.readouterr()
    assert code == 0
    assert "WARNING: stream rate" in captured.err
    assert "figures may be unreliable" in captured.err


def test_clean_short_capture_exits_0_without_watchdog(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install(monkeypatch, _FakeSession(samples=[_REAL] * 10))
    out = tmp_path / "clean.csv"
    code = dispatch(["capture", "-o", str(out), "-s", "30"])
    captured = capsys.readouterr()
    assert code == 0
    assert "WARNING: stream rate" not in captured.err  # wall < 0.5 s -> no watchdog
    assert len(out.read_text().splitlines()) == 1 + 10  # header + rows


def test_lost_samples_are_rows_of_0_2_ua_and_are_counted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install(monkeypatch, _FakeSession(samples=[_REAL, _NAN, _REAL, _NAN, _NAN]))
    out = tmp_path / "lossy.csv"
    code = dispatch(["capture", "-o", str(out), "-s", "30"])
    captured = capsys.readouterr()
    assert code == 0
    rows = out.read_text().splitlines()[1:]
    assert len(rows) == 5
    assert [r.split(",")[1] for r in rows].count("0.200") == 3
    assert "3 data-loss placeholder samples" in captured.err


def test_ctrl_c_flushes_csv_prints_interrupted_and_exits_130(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _install(monkeypatch, _FakeSession(samples=[], interrupt=True))
    out = tmp_path / "interrupted.csv"
    code = dispatch(["capture", "-o", str(out), "-s", "30"])
    captured = capsys.readouterr()
    assert code == 130
    assert "interrupted: CSV flushed" in captured.err
    # The partial CSV is valid: header + the one pre-interrupt row.
    assert len(out.read_text().splitlines()) == 1 + 1


def test_ppk2_output_records_a_lost_sample_as_0_2_ua(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """``--out x.ppk2`` writes a session file; a lost sample is 0.2 µA, as in the app."""
    _install(monkeypatch, _FakeSession(samples=[_REAL, _NAN, _REAL]))
    out = tmp_path / "trace.ppk2"

    code = dispatch(["capture", "-o", str(out), "-s", "0.1"])

    captured = capsys.readouterr()
    assert code == 0, captured.err
    currents = [current for current, _ in frames(out)]
    assert currents[0] == currents[2] == 12.5
    assert abs(currents[1] - 0.2) < 1e-6  # a float32
    assert [pairs for _, pairs in frames(out)] == [0x555A, 0x5555, 0x555A]
    assert "data-loss placeholder" in captured.err
