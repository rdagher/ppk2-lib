"""Pure-logic tests for the session internals.

Covers the chunked metadata-read accumulator without touching pyserial.
The full open / handshake path is HIL-tier (needs a real PPK2) and lives
in ``tests/hil/test_client.py``.
"""

from collections import deque
from dataclasses import replace
from time import monotonic
from typing import TYPE_CHECKING, cast

import pytest

from ppk2.client import session as session_module
from ppk2.client.session import (
    VOLTAGE_LIMIT_HARDWARE_MAX_MV,
    VOLTAGE_LIMIT_HARDWARE_MIN_MV,
    HandshakeFailed,
    Session,
    _recover_and_negotiate,  # pyright: ignore[reportPrivateUsage]
    read_until_end,
)
from ppk2.protocol import CalibrationCoefficients, Opcode, SpikeFilter
from tests.protocol.fixtures import METADATA_RAW, STREAM_BIN

if TYPE_CHECKING:
    import serial


def _identity_coeffs() -> CalibrationCoefficients:
    """Build a coefficients block with ``ug == (1.0,)*5`` and trivial values elsewhere."""
    return CalibrationCoefficients(
        calibrated=True,
        r=(1.0, 1.0, 1.0, 1.0, 1.0),
        gs=(0.0, 0.0, 0.0, 0.0, 0.0),
        gi=(1.0, 1.0, 1.0, 1.0, 1.0),
        o=(0.0, 0.0, 0.0, 0.0, 0.0),
        s=(0.0, 0.0, 0.0, 0.0, 0.0),
        i=(0.0, 0.0, 0.0, 0.0, 0.0),
        ug=(1.0, 1.0, 1.0, 1.0, 1.0),
        vdd_mv=3300,
        mode=1,
        hw=0,
        ia=0,
    )


class _RecordingPort:
    """Minimal ``serial.Serial``-shaped mock that records writes.

    Pyright accepts it after a :func:`cast` at the call site; the
    Session constructor never invokes anything we don't implement.
    """

    def __init__(self) -> None:
        """Initialise an empty write buffer."""
        self.written = bytearray()

    def write(self, data: bytes) -> int:
        """Append ``data`` to the recorded writes; return ``len(data)``."""
        self.written.extend(data)
        return len(data)


class _ChunkedReader:
    """Yields a queued sequence of byte chunks then returns ``b""`` forever.

    Mirrors pyserial's behaviour where ``read(n)`` returns empty bytes on
    timeout rather than blocking. Used to exercise ``read_until_end``'s
    accumulation contract without a real serial port.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        """Capture the chunk sequence the next reads will hand back."""
        self._chunks: deque[bytes] = deque(chunks)

    def read(self, n: int, /) -> bytes:
        """Return the next queued chunk (clipped to ``n``) or empty on exhaustion."""
        if not self._chunks:
            return b""
        chunk = self._chunks.popleft()
        if len(chunk) <= n:
            return chunk
        # Requeue the remainder so the next read gets it.
        self._chunks.appendleft(chunk[n:])
        return chunk[:n]


class _VanishingPort:
    """A port whose input flush fails the way a just re-enumerated device's does.

    pyserial raises a bare ``termios.error`` there, which is neither a
    ``SerialException`` nor an ``OSError``; any ``Exception`` stands in
    for it here, so the test also runs where ``termios`` does not exist.
    """

    def __init__(self, response: bytes) -> None:
        self._response = deque([response])
        self.in_waiting = 0

    def write(self, data: bytes) -> int:
        return len(data)

    def reset_input_buffer(self) -> None:
        raise RuntimeError(6, "Device not configured")

    def read(self, _n: int, /) -> bytes:
        return self._response.popleft() if self._response else b""


def test_handshake_survives_a_failing_input_flush() -> None:
    """The flush is best effort: its failure must not escape the handshake."""
    port = _VanishingPort(METADATA_RAW.read_bytes())

    coeffs = _recover_and_negotiate(cast("serial.Serial", port))

    assert coeffs.hw != 0


def test_read_until_end_accumulates_across_chunks() -> None:
    """Regression for the chunked-read case where END only appears in a later chunk."""
    header = b"Calibrated: 0\nR0: 1.0\n"
    tail = b"R1: 2.0\nEND\n"
    reader = _ChunkedReader([header, tail])

    got = read_until_end(reader, total_timeout_s=0.5)

    assert got == header + tail
    assert b"END" in got


def test_read_until_end_times_out_without_end() -> None:
    reader = _ChunkedReader([b"no terminator here\n"])
    with pytest.raises(TimeoutError):
        read_until_end(reader, total_timeout_s=0.15)


def test_read_until_end_handles_chunk_split_inside_end_token() -> None:
    """Even when END is split across reads it must be detected."""
    chunks = [b"Calibrated: 0\nR0: 1.0\nE", b"ND\n"]
    reader = _ChunkedReader(chunks)
    got = read_until_end(reader, total_timeout_s=0.5)
    assert got.endswith(b"END\n")


def test_session_set_user_gain_replaces_coeffs_ug_in_place() -> None:
    """Host-side override updates self._coeffs.ug; other arrays unchanged.

    Also pins the no-wire-write invariant: the firmware ignores
    SET_USER_GAINS (0x25) and only the host-side ug array affects
    calibration, so no frame is sent (see Session.set_user_gain).
    """
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.set_user_gain(2, 1.07)

    # Other ranges unaffected.
    assert session.coefficients().ug == (1.0, 1.0, 1.07, 1.0, 1.0)
    # No wire bytes: fully host-side.
    assert port.written == b""


def test_session_set_user_gain_after_start_measuring_raises() -> None:
    """Live capture's StreamParser can't pick up a mid-stream gain change."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    # Simulate that start_measuring already ran (without sending wire bytes
    # because the mock would need more API surface to drive the full path).
    session._measuring = True  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(RuntimeError, match="before start_measuring"):
        session.set_user_gain(0, 1.1)


def test_session_stop_measuring_reopens_configuration() -> None:
    """After a stop the pre-start setters work again."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())
    session._measuring = True  # pyright: ignore[reportPrivateUsage]

    session.stop_measuring()

    session.set_user_gain(0, 1.1)
    assert session.coefficients().ug[0] == 1.1


@pytest.mark.parametrize("gain", [0.89, 1.11, 5.0, float("nan")])
def test_session_set_user_gain_rejects_a_gain_outside_the_range_of_the_app(gain: float) -> None:
    session = Session(cast("serial.Serial", _RecordingPort()), _identity_coeffs())

    with pytest.raises(ValueError, match=r"from 0\.9 to 1\.1"):
        session.set_user_gain(2, gain)

    assert session.coefficients().ug == (1.0, 1.0, 1.0, 1.0, 1.0)


def test_session_resets_reported_user_gains_outside_the_range_of_the_app() -> None:
    """As Nordic's app at connect: one gain out of range, all five back to 1.0."""
    reported = replace(_identity_coeffs(), ug=(1.0, 1.05, 5.0, 1.0, 1.0))

    with pytest.warns(RuntimeWarning, match="all five are taken as 1.0"):
        session = Session(cast("serial.Serial", _RecordingPort()), reported)

    assert session.coefficients().ug == (1.0, 1.0, 1.0, 1.0, 1.0)


def test_session_keeps_reported_user_gains_inside_the_range() -> None:
    reported = replace(_identity_coeffs(), ug=(0.9, 1.05, 1.1, 1.0, 1.0))

    session = Session(cast("serial.Serial", _RecordingPort()), reported)

    assert session.coefficients().ug == (0.9, 1.05, 1.1, 1.0, 1.0)


def test_session_set_user_gain_propagates_value_error_on_bad_range() -> None:
    """Bad range_idx raises from set_user_gain's own range check before any state mutation."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    with pytest.raises(ValueError):
        session.set_user_gain(5, 1.05)

    # No wire bytes written; coefficients unchanged.
    assert port.written == b""
    assert session.coefficients().ug == (1.0, 1.0, 1.0, 1.0, 1.0)


def test_session_spike_filter_starts_at_defaults() -> None:
    """A freshly-built session reports the defaults of Nordic's app."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    assert session.spike_filter() == SpikeFilter()


def test_session_set_spike_filter_partial_update_keeps_other_knobs() -> None:
    """Setting just ``alpha`` leaves ``samples`` and ``alpha5`` untouched."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.set_spike_filter(alpha=0.5)

    sf = session.spike_filter()
    assert sf.alpha == 0.5
    assert sf.samples == SpikeFilter().samples
    assert sf.alpha5 == SpikeFilter().alpha5

    # No wire bytes: spike-filter is host-side only.
    assert port.written == b""


def test_session_set_spike_filter_all_three_knobs() -> None:
    """All three kwargs land on the dataclass in one call."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.set_spike_filter(samples=7, alpha=0.42, alpha5=0.04)

    assert session.spike_filter() == SpikeFilter(samples=7, alpha=0.42, alpha5=0.04)


def test_session_set_spike_filter_after_start_measuring_raises() -> None:
    """Live capture's StreamParser can't pick up a mid-stream filter change."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session._measuring = True  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(RuntimeError, match="before start_measuring"):
        session.set_spike_filter(alpha=0.5)


def test_session_set_spike_filter_rejects_invalid_alpha() -> None:
    """Out-of-range ``alpha`` surfaces from SpikeFilter's __post_init__."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    with pytest.raises(ValueError, match="alpha"):
        session.set_spike_filter(alpha=1.5)

    # State unchanged after the failed validation.
    assert session.spike_filter() == SpikeFilter()


def test_session_voltage_limit_defaults_to_hardware_max() -> None:
    """A freshly-built session lets the regulator run up to the hardware ceiling."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    assert session.voltage_limit() == VOLTAGE_LIMIT_HARDWARE_MAX_MV == 5000


def test_session_set_voltage_limit_lowers_ceiling() -> None:
    """Tightened limit is stored; existing supply voltage is untouched."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.set_voltage_limit(3300)

    assert session.voltage_limit() == 3300
    # set_voltage_limit is host-side only: no wire bytes.
    assert port.written == b""


def test_session_set_voltage_limit_clamps_to_hardware_bounds() -> None:
    """A limit above ``HARDWARE_MAX_MV`` collapses to the hardware ceiling."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.set_voltage_limit(9999)
    assert session.voltage_limit() == VOLTAGE_LIMIT_HARDWARE_MAX_MV

    session.set_voltage_limit(0)
    assert session.voltage_limit() == VOLTAGE_LIMIT_HARDWARE_MIN_MV


def test_session_set_source_voltage_above_limit_raises() -> None:
    """Requested voltage above the configured limit raises before any wire write."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.set_voltage_limit(2500)

    with pytest.raises(ValueError, match="exceeds voltage limit"):
        session.set_source_voltage(3300)

    # No wire bytes: limit failed before write.
    assert port.written == b""


def test_session_set_source_voltage_at_limit_passes() -> None:
    """At-the-limit request is allowed; wire write goes out at the requested value."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.set_voltage_limit(2500)
    session.set_source_voltage(2500)

    # REGULATOR_SET = 0x0D, MSB = 2500 >> 8 = 0x09, LSB = 2500 & 0xFF = 0xC4.
    assert port.written == bytes([0x0D, 0x09, 0xC4])


def test_session_set_voltage_limit_after_start_measuring_raises() -> None:
    """Mid-capture limit changes are surfaced explicitly, not deferred."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session._measuring = True  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(RuntimeError, match="before start_measuring"):
        session.set_voltage_limit(3300)


# ─── power_on catch-up + one-shot backlog drop ──────────────────────────


class _StreamingPort:
    """Serial mock with a read side: logs the read/write interleaving.

    ``read(n)`` returns ``b""`` (pyserial's timeout shape) so the
    drain loops spin on their deadline; the event log lets tests
    assert drains happen on the right side of the power-on write.
    """

    def __init__(self, backlog: bytes = b"", *, flowing: bool = False) -> None:
        """Start with a pending backlog, or ``flowing``: every read is full."""
        self.events: list[str] = []
        self.written = bytearray()
        self._backlog = backlog
        self._flowing = flowing

    def write(self, data: bytes) -> int:
        self.events.append(f"write:{data.hex()}")
        self.written.extend(data)
        return len(data)

    def read(self, n: int) -> bytes:
        self.events.append("read")
        if self._flowing:
            return b"\x00" * n
        chunk = self._backlog[:n]
        self._backlog = self._backlog[len(chunk) :]
        return chunk

    @property
    def in_waiting(self) -> int:
        return len(self._backlog)


_TOGGLE = f"write:{bytes([0x0C, 0x01]).hex()}"


def _measuring_session(port: _StreamingPort) -> Session:
    session = Session(cast("serial.Serial", port), _identity_coeffs())
    session.start_measuring()
    return session


def test_power_on_catches_up_with_the_stream_then_sends_the_command() -> None:
    """Reads first, past the 0.35 s in which the PPK2 holds commands; nothing after."""
    port = _StreamingPort(flowing=True)
    session = _measuring_session(port)
    started = monotonic()

    session.power_on()

    assert monotonic() - started >= 0.3
    assert "read" in port.events[: port.events.index(_TOGGLE)]
    assert port.events[-1] == _TOGGLE


def test_power_on_gives_up_catching_up_on_a_silent_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """No byte arrives: the command is still sent, after the cap."""
    monkeypatch.setattr("ppk2.client.session._CATCH_UP_CAP_S", 0.02)
    port = _StreamingPort()
    session = _measuring_session(port)

    session.power_on()

    assert port.events[-1] == _TOGGLE


def test_power_on_without_a_stream_sends_the_command_at_once() -> None:
    port = _StreamingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.power_on()

    assert port.events == [_TOGGLE]


def test_drop_pending_backlog_is_a_single_bounded_read() -> None:
    """One in_waiting-sized read: not a drain-until-empty loop."""
    port = _StreamingPort(backlog=b"\x00" * 4096)
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    dropped = session.drop_pending_backlog()

    assert dropped == 4096
    assert port.events == ["read"]  # exactly one read, no loop
    assert port.in_waiting == 0


def test_drop_pending_backlog_on_empty_buffer_reads_nothing() -> None:
    port = _StreamingPort(backlog=b"")
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    assert session.drop_pending_backlog() == 0
    assert port.events == []  # in_waiting == 0 -> no read at all


# ─── close waits for the stream to end ──────────────────────────────────


class _ClosingPort:
    """Serial mock for ``close``: a stream tail to read, then silence, and an event log."""

    def __init__(self, tail_reads: int | None) -> None:
        """``tail_reads`` reads return data before the silence; ``None`` never goes silent."""
        self.events: list[str] = []
        self.timeout: float | None = 0.1
        self.read_timeouts: set[float | None] = set()
        self._tail_reads = tail_reads

    def write(self, data: bytes) -> int:
        self.events.append(f"write:{data.hex()}")
        return len(data)

    def read(self, n: int) -> bytes:
        self.read_timeouts.add(self.timeout)
        if self._tail_reads is None:
            self.events.append("read:data")
            return b"\x00" * 4
        if self._tail_reads > 0:
            self._tail_reads -= 1
            self.events.append("read:data")
            return b"\x00" * min(n, 4096)
        self.events.append("read:quiet")
        return b""

    def close(self) -> None:
        self.events.append("close")


def test_close_reads_the_stream_out_before_closing_the_port() -> None:
    """Stop and power-off go out, the tail is read until silence, then the port closes."""
    port = _ClosingPort(tail_reads=3)
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.close()

    stop = f"write:{bytes([Opcode.AVERAGE_STOP.byte()]).hex()}"
    fet_off = f"write:{bytes([Opcode.DEVICE_RUNNING_SET.byte(), 0x00]).hex()}"
    assert port.events == [
        stop,
        fet_off,
        "read:data",
        "read:data",
        "read:data",
        "read:quiet",
        "close",
    ]
    assert port.read_timeouts == {0.05}


def test_close_gives_up_on_a_stream_that_never_stops() -> None:
    """A PPK2 that keeps streaming does not hold ``close`` for more than its cap."""
    port = _ClosingPort(tail_reads=None)
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    started = monotonic()
    session.close()

    assert monotonic() - started < 1.0
    assert port.events[-1] == "close"


def test_close_twice_touches_the_port_once() -> None:
    port = _ClosingPort(tail_reads=0)
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.close()
    session.close()

    assert port.events.count("close") == 1


def test_stop_measuring_reads_the_stream_out_and_keeps_the_read_timeout() -> None:
    """The end of the stream is read before the session goes on, with its timeout restored."""
    port = _ClosingPort(tail_reads=2)
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.stop_measuring()

    stop = f"write:{bytes([Opcode.AVERAGE_STOP.byte()]).hex()}"
    assert port.events == [stop, "read:data", "read:data", "read:quiet"]
    assert port.timeout == 0.1


def test_a_failed_handshake_releases_the_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Left open, the port keeps its lock and the next open attempt fails on it."""
    opened: list[_ClosingPort] = []

    def fake_serial(*_args: object, **_kwargs: object) -> _ClosingPort:
        opened.append(_ClosingPort(tail_reads=0))
        return opened[-1]

    def no_answer(_port: object) -> CalibrationCoefficients:
        raise HandshakeFailed(3, "read metadata: no END")

    monkeypatch.setattr(session_module.serial, "Serial", fake_serial)
    monkeypatch.setattr(session_module, "_empty_serial", lambda _port: None)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    monkeypatch.setattr(session_module, "_recover_and_negotiate", no_answer)
    monkeypatch.setattr(session_module, "sleep", lambda _s: None)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]

    with pytest.raises(HandshakeFailed):
        Session.open("/dev/does-not-matter")

    assert opened, "no open attempt was made"
    assert all(port.events[-1] == "close" for port in opened)


def test_capture_stops_on_a_silent_port_when_keep_going_says_so() -> None:
    """A port that sends nothing never reaches emit: keep_going ends the capture."""
    session = Session(cast("serial.Serial", _ChunkedReader([])), _identity_coeffs())
    calls = 0

    def keep_going() -> bool:
        nonlocal calls
        calls += 1
        return calls < 3

    session.capture(lambda _sample: True, keep_going=keep_going)

    assert calls == 3


def test_capture_does_not_call_emit_again_after_it_returns_false() -> None:
    """One read holds 600 samples; emit says stop at the first and is left alone."""
    stream = STREAM_BIN.read_bytes()
    session = Session(cast("serial.Serial", _ChunkedReader([stream])), _identity_coeffs())
    seen = 0

    def emit(_sample: object) -> bool:
        nonlocal seen
        seen += 1
        return False

    session.capture(emit)

    assert seen == 1


def test_capture_asks_keep_going_when_the_bytes_hold_no_sample() -> None:
    """Three bytes are no sample: emit is never called, keep_going still ends it."""
    port = _ChunkedReader([b"\x00\x00\x00"])
    session = Session(cast("serial.Serial", port), _identity_coeffs())
    calls = 0

    def keep_going() -> bool:
        nonlocal calls
        calls += 1
        return False

    session.capture(lambda _sample: True, keep_going=keep_going)

    assert calls == 1
