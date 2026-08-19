"""Pure-logic tests for the session internals.

Covers the chunked metadata-read accumulator without touching pyserial.
The full open / handshake path is HIL-tier (needs a real PPK2) and lives
in ``tests/client/test_hardware.py``.
"""

from collections import deque
from typing import TYPE_CHECKING, cast

import pytest

from ppk2.client.session import (
    VOLTAGE_LIMIT_HARDWARE_MAX_MV,
    VOLTAGE_LIMIT_HARDWARE_MIN_MV,
    Session,
    read_until_end,
)
from ppk2.protocol import CalibrationCoefficients, SpikeFilter

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
    # No wire bytes — fully host-side.
    assert port.written == b""


def test_session_set_user_gain_after_start_measuring_raises() -> None:
    """Live capture's StreamParser can't pick up a mid-stream gain change."""
    port = _RecordingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    # Simulate that start_measuring already ran (without sending wire bytes
    # because the mock would need more API surface to drive the full path).
    session._measuring = True  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(RuntimeError, match="before start_measuring"):
        session.set_user_gain(0, 1.5)


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
    """A freshly-built session reports the Nordic-GUI default knobs."""
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

    # No wire bytes — spike-filter is host-side only.
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
    """Tightened limit is stored; existing setpoint is untouched."""
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

    # No wire bytes — limit failed before write.
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


# ─── power_on latch + one-shot backlog drop ─────────────────────────────


class _StreamingPort:
    """Serial mock with a read side: logs the read/write interleaving.

    ``read(n)`` returns ``b""`` (pyserial's timeout shape) so the
    drain loops spin on their deadline; the event log lets tests
    assert drains happen on the right side of the FET-toggle write.
    """

    def __init__(self, backlog: bytes = b"") -> None:
        """Start with an optional pending input backlog."""
        self.events: list[str] = []
        self.written = bytearray()
        self._backlog = backlog

    def write(self, data: bytes) -> int:
        self.events.append(f"write:{data.hex()}")
        self.written.extend(data)
        return len(data)

    def read(self, n: int) -> bytes:
        self.events.append("read")
        chunk = self._backlog[:n]
        self._backlog = self._backlog[len(chunk) :]
        return chunk

    @property
    def in_waiting(self) -> int:
        return len(self._backlog)


def test_power_on_pre_drains_then_toggles_then_latches() -> None:
    """Drain ~0.3 s BEFORE the FET toggle, toggle, then drain latch_s after."""
    port = _StreamingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.power_on(latch_s=0.05)

    toggle = f"write:{bytes([0x0C, 0x01]).hex()}"
    assert toggle in port.events
    toggle_at = port.events.index(toggle)
    # Reads on both sides of the toggle: the pre-drain and the latch drain.
    assert "read" in port.events[:toggle_at], "no pre-toggle drain"
    assert "read" in port.events[toggle_at + 1 :], "no post-toggle latch drain"
    assert port.written == bytes([0x0C, 0x01])


def test_power_on_latch_zero_skips_the_post_toggle_drain() -> None:
    """latch_s=0 hands the latch to the capture loop — no reads after the toggle."""
    port = _StreamingPort()
    session = Session(cast("serial.Serial", port), _identity_coeffs())

    session.power_on(latch_s=0.0)

    toggle = f"write:{bytes([0x0C, 0x01]).hex()}"
    toggle_at = port.events.index(toggle)
    assert "read" in port.events[:toggle_at]  # pre-drain still runs
    assert "read" not in port.events[toggle_at + 1 :]
    # The toggle is the last event: the capture loop takes over from here.
    assert port.events[-1] == toggle


def test_drop_pending_backlog_is_a_single_bounded_read() -> None:
    """One in_waiting-sized read — not a drain-until-empty loop."""
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
    assert port.events == []  # in_waiting == 0 → no read at all
