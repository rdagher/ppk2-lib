"""Top-level error-mapping tests: dispatch() turns failures into exit codes.

Every test stubs the device-resolution seam, so no discovery poll or
serial I/O ever runs.
"""

from collections.abc import Callable

import pytest
import serial

from ppk2 import NotFound, SerialIOError
from ppk2.cli.commands import discover as discover_module
from ppk2.cli.main import dispatch, errno16_in_chain


def _raiser(exc: BaseException) -> Callable[[str | None, str | None], str]:
    def raise_it(_serial: str | None, _port: str | None) -> str:
        raise exc

    return raise_it


def test_discovery_error_maps_to_one_line_stderr_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(discover_module, "resolve_device", _raiser(NotFound()))
    code = dispatch(["discover"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("error: no PPK2 found")
    assert "Traceback" not in captured.err


def test_session_error_with_errno16_cause_appends_gui_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The EBUSY hint surfaces even when the errno hides inside a wrapped cause."""
    cause = serial.SerialException(16, "could not open port /dev/x: Resource busy")
    err = SerialIOError("serial open: Resource busy")
    err.__cause__ = cause
    monkeypatch.setattr(discover_module, "resolve_device", _raiser(err))
    code = dispatch(["discover"])
    captured = capsys.readouterr()
    assert code == 1
    assert "close the nRF Connect Power Profiler" in captured.err


def test_bare_serial_exception_maps_to_serial_io_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        discover_module, "resolve_device", _raiser(serial.SerialException("device reports error"))
    )
    code = dispatch(["discover"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("error: serial I/O failed")
    assert "nRF Connect Power Profiler" not in captured.err  # no errno 16 -> no hint


def test_keyboard_interrupt_outside_capture_maps_to_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ctrl-C in a non-capture command -> conventional 130, no traceback.

    Typer converts an in-command KeyboardInterrupt to a silent exit
    130 itself; the exit code is the automation contract. The
    capture command prints its own richer message on interrupt.
    """
    monkeypatch.setattr(discover_module, "resolve_device", _raiser(KeyboardInterrupt()))
    code = dispatch(["discover"])
    captured = capsys.readouterr()
    assert code == 130
    assert "Traceback" not in captured.err


def test_usage_error_keeps_click_rendering_and_exit_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = dispatch(["capture"])  # --out is required
    captured = capsys.readouterr()
    assert code == 2
    assert "out" in captured.err.lower()


def test_success_path_returns_0(capsys: pytest.CaptureFixture[str]) -> None:
    code = dispatch(["discover", "--port", "/dev/cu.usbmodemFAKE"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "/dev/cu.usbmodemFAKE"


def test_errno16_detected_through_cause_chain() -> None:
    inner = OSError(16, "Resource busy")
    middle = SerialIOError("wrapped once")
    middle.__cause__ = inner
    outer = SerialIOError("wrapped twice")
    outer.__cause__ = middle
    assert errno16_in_chain(outer)
    assert not errno16_in_chain(SerialIOError("no errno anywhere"))
    assert not errno16_in_chain(OSError(13, "permission denied"))


def test_an_output_that_cannot_be_written_is_one_error_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An OSError from the output file: one line naming the path, exit 1, no traceback."""
    error = PermissionError(13, "Permission denied", "/read-only/trace.csv")
    monkeypatch.setattr(discover_module, "resolve_device", _raiser(error))
    assert dispatch(["discover"]) == 1
    assert capsys.readouterr().err == "error: /read-only/trace.csv: Permission denied\n"
