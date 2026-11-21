"""Unit tests for ``ppk2 capture --user-gain`` parsing + wiring."""

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from ppk2.cli.commands.capture import parse_user_gain_spec
from ppk2.cli.main import app
from tests.cli.test_smoke import stub_device_seam

runner = CliRunner()


# ── Helper-level parsing ────────────────────────────────────────────────


def test_parse_user_gain_simple() -> None:
    assert parse_user_gain_spec("2:1.05") == (2, 1.05)


def test_parse_user_gain_tolerates_whitespace() -> None:
    assert parse_user_gain_spec(" 0 : 0.99 ") == (0, 0.99)


def test_parse_user_gain_zero_range_and_unit_gain() -> None:
    assert parse_user_gain_spec("0:1.0") == (0, 1.0)


def test_parse_user_gain_high_range() -> None:
    assert parse_user_gain_spec("4:0.9") == (4, 0.9)


@pytest.mark.parametrize("gain_str", ["0.5", "0.89", "1.11", "5"])
def test_parse_user_gain_rejects_a_gain_outside_the_range_of_the_app(gain_str: str) -> None:
    with pytest.raises(typer.BadParameter, match=r"from 0\.9 to 1\.1"):
        parse_user_gain_spec(f"2:{gain_str}")


@pytest.mark.parametrize(
    "spec",
    [
        "garbage",  # no colon at all
        "2:1.05:extra",  # too many colons
        ":1.0",  # missing range
        "2:",  # missing gain
        "",  # empty
    ],
)
def test_parse_user_gain_rejects_malformed_shape(spec: str) -> None:
    with pytest.raises(typer.BadParameter, match="--user-gain"):
        parse_user_gain_spec(spec)


@pytest.mark.parametrize("range_str", ["-1", "5", "10", "foo"])
def test_parse_user_gain_rejects_invalid_range(range_str: str) -> None:
    with pytest.raises(typer.BadParameter, match="--user-gain"):
        parse_user_gain_spec(f"{range_str}:1.05")


@pytest.mark.parametrize("gain_str", ["nan", "inf", "-inf", "abc"])
def test_parse_user_gain_rejects_invalid_gain(gain_str: str) -> None:
    with pytest.raises(typer.BadParameter, match="--user-gain"):
        parse_user_gain_spec(f"2:{gain_str}")


# ── CLI wiring ─────────────────────────────────────────────────────────


def test_capture_help_documents_user_gain_flag() -> None:
    result = runner.invoke(app, ["capture", "--help"])
    assert result.exit_code == 0
    assert "--user-gain" in result.output
    assert "RANGE:GAIN" in result.output


def test_capture_rejects_malformed_user_gain_at_runtime() -> None:
    """A bad --user-gain value should surface as a Typer parse error, not a hardware crash."""
    result = runner.invoke(
        app,
        [
            "capture",
            "--out",
            "/tmp/_unused.csv",
            "--seconds",
            "0.1",
            "--user-gain",
            "garbage",
        ],
    )
    assert result.exit_code != 0
    # The error mentions the flag: the helper raises typer.BadParameter.
    assert "--user-gain" in result.output or "user-gain" in result.output.lower()


def test_capture_accepts_repeated_user_gain_at_parse_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--user-gain`` repeated twice must parse cleanly (no help dump)."""
    stub_device_seam(monkeypatch)
    result = runner.invoke(
        app,
        [
            "capture",
            "--out",
            str(tmp_path / "unused.csv"),
            "--seconds",
            "0.1",
            "--user-gain",
            "0:1.0",
            "--user-gain",
            "4:0.95",
        ],
    )
    # The stubbed session captures zero samples (exit code irrelevant),
    # but the absence of a Usage: line proves parse succeeded.
    assert "Usage:" not in result.output
