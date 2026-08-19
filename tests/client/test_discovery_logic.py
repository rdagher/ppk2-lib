"""Pure-logic tests for discovery — covers the dual-VCOM cases without pyserial.

The pure ``find_group_in``/``find_group_in_by_serial``/``group_ppk2s``
helpers take a list of ``RawPort`` rows so we can test the macOS-style
dual-VCOM enumeration ambiguity without touching real hardware; the
probe-driven paths take an injected probe function (and a monkeypatched
``enumerate_ports``) for the same reason — no serial port is ever
opened in this file.
"""

import pytest

from ppk2.client import discovery
from ppk2.client.discovery import (
    PPK2_PID,
    PPK2_VID,
    Ambiguous,
    DataPortNotFound,
    NotFound,
    PortInfo,
    PortStatus,
    RawPort,
    build_listings,
    classify_ports,
    find_group_in,
    find_group_in_by_serial,
    find_ppk2,
    find_ppk2_by_serial,
    group_ppk2s,
    lex_lowest,
    looks_like_ppk2,
    probe_data_port,
)


def _ppk2_port(device: str, serial_number: str) -> RawPort:
    """Synthesise a :class:`RawPort` that ``looks_like_ppk2`` accepts."""
    return RawPort(
        device=device,
        vid=PPK2_VID,
        pid=PPK2_PID,
        serial_number=serial_number,
    )


def _segger_jlink_port(device: str) -> RawPort:
    """Synthesise a SEGGER J-Link port (e.g., the embedded debugger on an
    nRF DK) — must be filtered out even though it shares OS-level
    metadata patterns with the PPK2.
    """
    return RawPort(
        device=device,
        vid=0x1366,
        pid=0x1069,
        serial_number="000123456789",
    )


def test_empty_port_list_is_not_found() -> None:
    with pytest.raises(NotFound):
        find_group_in([])


def test_single_ppk2_with_two_vcoms_returns_lex_lowest() -> None:
    """macOS dual-VCOM: both ports map to the same physical PPK2; pick lex-lowest.

    Path values mirror a real macOS dual-VCOM enumeration. ``A12``
    (lex-lower) is the 100 kSPS data port; ``A14`` is the idle /
    control interface.
    """
    ports = [
        _ppk2_port("/dev/cu.usbmodemA1B2C3D4E5F64", "A1B2C3D4E5F6"),
        _ppk2_port("/dev/cu.usbmodemA1B2C3D4E5F62", "A1B2C3D4E5F6"),
        _segger_jlink_port("/dev/cu.usbmodem0001234567891"),
    ]
    serial_str, paths = find_group_in(ports)
    info = PortInfo(device=lex_lowest(list(paths)), usb_serial=serial_str)
    assert info.device == "/dev/cu.usbmodemA1B2C3D4E5F62"
    assert info.usb_serial == "A1B2C3D4E5F6"


def test_looks_like_ppk2_requires_vid_and_pid() -> None:
    """VID/PID is the filter; product strings are never consulted."""
    assert looks_like_ppk2(_ppk2_port("/dev/cu.usbmodemX", "S"))
    assert not looks_like_ppk2(_segger_jlink_port("/dev/cu.usbmodemJ"))
    # Right VID, wrong PID (e.g. an nRF DK in some other Nordic mode).
    assert not looks_like_ppk2(
        RawPort(device="/dev/cu.usbmodemY", vid=PPK2_VID, pid=0x0001, serial_number="S")
    )
    # Right PID, wrong VID.
    assert not looks_like_ppk2(
        RawPort(device="/dev/cu.usbmodemZ", vid=0x0001, pid=PPK2_PID, serial_number="S")
    )
    # Missing identifiers.
    assert not looks_like_ppk2(
        RawPort(device="/dev/cu.usbmodemQ", vid=None, pid=None, serial_number="S")
    )


def test_two_physical_ppk2s_are_ambiguous() -> None:
    ports = [
        _ppk2_port("/dev/cu.usbmodemAAA1", "AAA"),
        _ppk2_port("/dev/cu.usbmodemAAA2", "AAA"),
        _ppk2_port("/dev/cu.usbmodemBBB1", "BBB"),
    ]
    with pytest.raises(Ambiguous) as exc:
        find_group_in(ports)
    assert exc.value.count == 2


def test_by_serial_picks_the_named_device() -> None:
    ports = [
        _ppk2_port("/dev/cu.usbmodemAAA1", "AAA"),
        _ppk2_port("/dev/cu.usbmodemBBB2", "BBB"),
        _ppk2_port("/dev/cu.usbmodemBBB1", "BBB"),
    ]
    serial_str, paths = find_group_in_by_serial(ports, "BBB")
    info = PortInfo(device=lex_lowest(list(paths)), usb_serial=serial_str)
    assert info.device == "/dev/cu.usbmodemBBB1"
    assert info.usb_serial == "BBB"


def test_by_serial_missing_raises_not_found() -> None:
    ports = [_ppk2_port("/dev/cu.usbmodemAAA1", "AAA")]
    with pytest.raises(NotFound):
        find_group_in_by_serial(ports, "MISSING")


def test_ports_without_usb_serial_are_skipped() -> None:
    """A PPK2-VID/PID port with no USB serial can't be grouped — dropped silently."""
    ports = [
        RawPort(
            device="/dev/cu.usbmodemX",
            vid=PPK2_VID,
            pid=PPK2_PID,
            serial_number=None,
        ),
        _ppk2_port("/dev/cu.usbmodemAAA1", "AAA"),
    ]
    serial_str, paths = find_group_in(ports)
    info = PortInfo(device=lex_lowest(list(paths)), usb_serial=serial_str)
    assert info.usb_serial == "AAA"


def test_group_ppk2s_returns_serial_keyed_dict() -> None:
    ports = [
        _ppk2_port("/dev/cu.usbmodemAAA1", "AAA"),
        _ppk2_port("/dev/cu.usbmodemAAA2", "AAA"),
        _ppk2_port("/dev/cu.usbmodemBBB1", "BBB"),
        _segger_jlink_port("/dev/cu.usbmodemJ"),
    ]
    groups = group_ppk2s(ports)
    assert set(groups) == {"AAA", "BBB"}
    assert sorted(groups["AAA"]) == ["/dev/cu.usbmodemAAA1", "/dev/cu.usbmodemAAA2"]


# ─── active data-port probe (injected probe fn — no serial I/O) ─────────


class _ScriptedProbe:
    """Probe double: answers from a path→status map, records call order."""

    def __init__(self, statuses: dict[str, PortStatus]) -> None:
        self.statuses = statuses
        self.calls: list[str] = []

    def __call__(self, path: str) -> PortStatus:
        self.calls.append(path)
        return self.statuses[path]


def test_probe_data_port_stops_at_lex_lowest_data_hit() -> None:
    """The lex-lowest candidate answers → the second VCOM is never opened."""
    probe = _ScriptedProbe({"/dev/A12": "data", "/dev/A14": "idle"})
    got = probe_data_port(("/dev/A14", "/dev/A12"), probe)
    assert got == "/dev/A12"
    assert probe.calls == ["/dev/A12"]


def test_probe_data_port_walks_past_idle_candidates() -> None:
    probe = _ScriptedProbe({"/dev/A12": "idle", "/dev/A14": "data"})
    got = probe_data_port(("/dev/A12", "/dev/A14"), probe)
    assert got == "/dev/A14"
    assert probe.calls == ["/dev/A12", "/dev/A14"]


def test_probe_data_port_returns_none_when_nothing_answers() -> None:
    probe = _ScriptedProbe({"/dev/A12": "busy", "/dev/A14": "idle"})
    assert probe_data_port(("/dev/A12", "/dev/A14"), probe) is None
    assert probe.calls == ["/dev/A12", "/dev/A14"]


def test_classify_ports_marks_unprobed_rest_idle_after_data_hit() -> None:
    """Stop-at-first-data: the remaining VCOMs are idle by definition, unprobed."""
    probe = _ScriptedProbe({"/dev/A12": "data", "/dev/A14": "busy"})
    statuses = classify_ports(("/dev/A12", "/dev/A14"), probe)
    assert statuses == {"/dev/A12": "data", "/dev/A14": "idle"}
    assert probe.calls == ["/dev/A12"]  # A14 never opened


def test_classify_ports_probes_everything_when_no_data_port() -> None:
    """No data hit → every path probed so busy and idle separate in the output."""
    probe = _ScriptedProbe({"/dev/A12": "busy", "/dev/A14": "idle"})
    statuses = classify_ports(("/dev/A12", "/dev/A14"), probe)
    assert statuses == {"/dev/A12": "busy", "/dev/A14": "idle"}
    assert probe.calls == ["/dev/A12", "/dev/A14"]


def test_build_listings_one_block_per_device_sorted_by_serial() -> None:
    ports = [
        _ppk2_port("/dev/cu.usbmodemBBB4", "BBB"),
        _ppk2_port("/dev/cu.usbmodemBBB2", "BBB"),
        _ppk2_port("/dev/cu.usbmodemAAA2", "AAA"),
        _ppk2_port("/dev/cu.usbmodemAAA4", "AAA"),
        _segger_jlink_port("/dev/cu.usbmodemJ"),
    ]
    probe = _ScriptedProbe(
        {
            "/dev/cu.usbmodemAAA2": "data",
            "/dev/cu.usbmodemBBB2": "busy",
            "/dev/cu.usbmodemBBB4": "idle",
        }
    )
    listings = build_listings(ports, probe)
    assert [listing.usb_serial for listing in listings] == ["AAA", "BBB"]

    aaa, bbb = listings
    assert aaa.ports == ("/dev/cu.usbmodemAAA2", "/dev/cu.usbmodemAAA4")
    assert aaa.data_port == "/dev/cu.usbmodemAAA2"
    assert aaa.statuses["/dev/cu.usbmodemAAA4"] == "idle"  # unprobed after the hit

    assert bbb.data_port is None
    assert bbb.statuses == {
        "/dev/cu.usbmodemBBB2": "busy",
        "/dev/cu.usbmodemBBB4": "idle",
    }


def test_find_ppk2_probes_inside_the_poll_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A device that enumerates but answers only on a later tick still resolves.

    Tick 1: both VCOMs probe idle (firmware not up yet). Tick 2: the
    lex-lowest answers. Probing inside the retry loop lets a device
    that enumerates before its firmware answers still resolve.
    """
    ports = [
        _ppk2_port("/dev/cu.usbmodemX2", "XXX"),
        _ppk2_port("/dev/cu.usbmodemX4", "XXX"),
    ]
    monkeypatch.setattr(discovery, "enumerate_ports", lambda: ports)

    calls: list[str] = []

    def probe(path: str) -> PortStatus:
        calls.append(path)
        # First full pass (2 candidates) sees nothing; then the data
        # port starts answering.
        return "data" if len(calls) > 2 and path == "/dev/cu.usbmodemX2" else "idle"

    got = find_ppk2(timeout_s=2.0, probe=probe)
    assert got.device == "/dev/cu.usbmodemX2"
    assert got.usb_serial == "XXX"
    assert len(calls) > 2  # needed more than the first pass


def test_find_ppk2_raises_data_port_not_found_with_gui_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Enumerated-but-silent device → DataPortNotFound with the actionable hint."""
    ports = [
        _ppk2_port("/dev/cu.usbmodemX2", "XXX"),
        _ppk2_port("/dev/cu.usbmodemX4", "XXX"),
    ]
    monkeypatch.setattr(discovery, "enumerate_ports", lambda: ports)

    with pytest.raises(DataPortNotFound) as exc:
        find_ppk2(timeout_s=0.0, probe=lambda _path: "busy")
    message = str(exc.value)
    assert "nRF Connect Power Profiler" in message
    assert "--port" in message
    assert exc.value.paths == ("/dev/cu.usbmodemX2", "/dev/cu.usbmodemX4")


def test_find_ppk2_by_serial_uses_the_probe_too(monkeypatch: pytest.MonkeyPatch) -> None:
    ports = [
        _ppk2_port("/dev/cu.usbmodemAAA2", "AAA"),
        _ppk2_port("/dev/cu.usbmodemBBB2", "BBB"),
        _ppk2_port("/dev/cu.usbmodemBBB4", "BBB"),
    ]
    monkeypatch.setattr(discovery, "enumerate_ports", lambda: ports)

    probe = _ScriptedProbe({"/dev/cu.usbmodemBBB2": "idle", "/dev/cu.usbmodemBBB4": "data"})
    got = find_ppk2_by_serial("BBB", timeout_s=0.0, probe=probe)
    assert got.device == "/dev/cu.usbmodemBBB4"
    # The other device's ports were never touched.
    assert "/dev/cu.usbmodemAAA2" not in probe.calls


def test_not_found_message_cites_vid_pid_not_product_strings() -> None:
    """The filter is USB VID/PID; the diagnostic must not mention product strings."""
    with pytest.raises(NotFound) as exc:
        find_group_in([])
    message = str(exc.value)
    assert "1915" in message and "C00A" in message
    assert "product" not in message.lower()
