"""CLI parse-path smoke tests: verify Typer wiring without touching hardware.

Every subcommand's help text renders cleanly, default flag values land,
required flags raise the right error, and ``--`` separates
``ppk2 run``'s child command from the CLI's own flags.
"""

from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ppk2 import Sample
from ppk2.cli.commands import capture as capture_module
from ppk2.cli.main import app

runner = CliRunner()


class _StubSession:
    """Zero-sample stand-in for ppk2.Session: same device seam that
    tests/cli/test_capture_semantics.py stubs, so no discovery poll or
    serial I/O ever runs. Doubles as its own ``Session.open`` surface.
    """

    def open(self, _device: str) -> "_StubSession":
        return self

    def __enter__(self) -> "_StubSession":
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

    def capture(
        self,
        emit: Callable[[Sample], bool],
        on_dataloss: Callable[[int], None] | None = None,
        keep_going: Callable[[], bool] | None = None,
    ) -> None:
        del emit, on_dataloss, keep_going


def _fake_resolve(_serial: str | None, _port: str | None) -> str:
    return "/dev/fake"


def stub_device_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the capture command's device seam with the no-op doubles."""
    monkeypatch.setattr(capture_module, "resolve_device", _fake_resolve)
    monkeypatch.setattr(capture_module, "Session", _StubSession())


def test_root_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Power Profiler Kit II" in result.output


def test_version_subcommand_prints_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    from ppk2 import __version__

    assert __version__ in result.output


def test_discover_help_lists_serial_flag() -> None:
    result = runner.invoke(app, ["discover", "--help"])
    assert result.exit_code == 0
    assert "--serial" in result.output


def test_metadata_help_runs() -> None:
    result = runner.invoke(app, ["metadata", "--help"])
    assert result.exit_code == 0


def test_power_help_documents_state_argument() -> None:
    result = runner.invoke(app, ["power", "--help"])
    assert result.exit_code == 0
    assert "on" in result.output.lower()
    assert "off" in result.output.lower()


def test_power_requires_state_argument() -> None:
    """``ppk2 power`` without ``on|off`` must fail at parse time, not at run time."""
    result = runner.invoke(app, ["power"])
    assert result.exit_code != 0


def test_capture_requires_out_flag() -> None:
    """``--out`` is required; absence is a parse error."""
    result = runner.invoke(app, ["capture"])
    assert result.exit_code != 0
    assert "--out" in result.output or "out" in result.output.lower()


def test_capture_help_documents_seconds_default() -> None:
    result = runner.invoke(app, ["capture", "--help"])
    assert result.exit_code == 0
    # Default value 30 (or 30.0) should appear in the help.
    assert "30" in result.output


def test_run_help_runs() -> None:
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0


def test_capture_seconds_flag_accepts_float(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--seconds 2.5`` must parse: failing means we mistyped the argument."""
    stub_device_seam(monkeypatch)
    result = runner.invoke(
        app, ["capture", "--out", str(tmp_path / "unused.csv"), "--seconds", "2.5"]
    )
    # Exit code can be anything (the stub captures zero samples), but
    # the help-output sentinel proves it didn't fail at parse time.
    assert "Usage:" not in result.output


def test_list_help_runs() -> None:
    result = runner.invoke(app, ["list", "--help"])
    assert result.exit_code == 0


def test_every_device_command_documents_port_flag() -> None:
    """``--port`` (bypass discovery + probe) exists on every device-touching command."""
    for command in ("discover", "metadata", "power", "capture", "run"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output, f"{command} --help lacks --port"


def test_discover_with_port_echoes_it_without_discovery() -> None:
    """--port bypasses discovery AND the probe: works with no PPK2 plugged in."""
    result = runner.invoke(app, ["discover", "--port", "/dev/cu.usbmodemFAKE12"])
    assert result.exit_code == 0
    assert result.output.strip() == "/dev/cu.usbmodemFAKE12"
