"""``ppk2 list`` rendering tests — device enumeration stubbed, no serial I/O."""

import pytest
from typer.testing import CliRunner

from ppk2 import Ppk2Listing
from ppk2.cli.commands import list_devices as list_devices_module
from ppk2.cli.main import app

runner = CliRunner()


def _patch_listings(monkeypatch: pytest.MonkeyPatch, listings: list[Ppk2Listing]) -> None:
    monkeypatch.setattr(list_devices_module, "list_ppk2s", lambda: listings)


def test_list_prints_one_block_per_device_with_status_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_listings(
        monkeypatch,
        [
            Ppk2Listing(
                usb_serial="A1B2C3D4E5F6",
                ports=("/dev/cu.usbmodemA1B2C3D4E5F62", "/dev/cu.usbmodemA1B2C3D4E5F64"),
                data_port="/dev/cu.usbmodemA1B2C3D4E5F62",
                statuses={
                    "/dev/cu.usbmodemA1B2C3D4E5F62": "data",
                    "/dev/cu.usbmodemA1B2C3D4E5F64": "idle",
                },
            )
        ],
    )
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "PPK2  serial=A1B2C3D4E5F6" in result.output
    assert "/dev/cu.usbmodemA1B2C3D4E5F62   [data port]" in result.output
    assert "/dev/cu.usbmodemA1B2C3D4E5F64   [idle]" in result.output


def test_list_flags_busy_port_and_exits_1_when_data_port_unidentified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_listings(
        monkeypatch,
        [
            Ppk2Listing(
                usb_serial="HELDBYGUI",
                ports=("/dev/cu.usbmodemH2", "/dev/cu.usbmodemH4"),
                data_port=None,
                statuses={
                    "/dev/cu.usbmodemH2": "busy",
                    "/dev/cu.usbmodemH4": "idle",
                },
            )
        ],
    )
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "[busy — held by another process?]" in result.output
    assert "close the nRF Connect Power Profiler" in result.output
    assert "--port" in result.output


def test_list_mixed_devices_exit_code_follows_the_unidentified_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One healthy device + one unidentified → still exit 1."""
    _patch_listings(
        monkeypatch,
        [
            Ppk2Listing(
                usb_serial="AAA",
                ports=("/dev/cu.usbmodemA2",),
                data_port="/dev/cu.usbmodemA2",
                statuses={"/dev/cu.usbmodemA2": "data"},
            ),
            Ppk2Listing(
                usb_serial="BBB",
                ports=("/dev/cu.usbmodemB2",),
                data_port=None,
                statuses={"/dev/cu.usbmodemB2": "idle"},
            ),
        ],
    )
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "serial=AAA" in result.output
    assert "serial=BBB" in result.output


def test_list_no_devices_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_listings(monkeypatch, [])
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 1
    assert "no PPK2 found" in result.output
