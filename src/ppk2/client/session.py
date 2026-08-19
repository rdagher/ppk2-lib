"""PPK2 session lifecycle — open, mode, stream, teardown.

Implements the PPK2 setup and teardown sequence (recover -> negotiate
metadata -> mode -> stream -> close). The Python idiom for "automatic
teardown on scope exit" is a context manager — [`Session`][] is
designed to be used with ``with``.

>>> with Session.open(port) as s:
...     s.set_mode(Mode.AMPERE)
...     s.set_source_voltage(3300)
...     s.start_measuring()
...     s.power_on()
...     s.capture(lambda sample: True)
"""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from enum import IntEnum
from time import monotonic, sleep
from typing import Protocol

import serial

from ppk2.protocol import (
    CalibrationCoefficients,
    MetadataError,
    Opcode,
    RangeArray,
    Sample,
    SpikeFilter,
    StreamParser,
    parse_metadata,
)

_BAUD_RATE = 115_200
_READ_TIMEOUT_S = 0.1
_OPEN_SETTLE_S = 0.05
_START_MEASURING_SETTLE_S = 0.2  # see Session.start_measuring for what this guards against
_POWER_ON_PRE_DRAIN_S = 0.3  # clear the backlog so the FET toggle lands on a live stream
_METADATA_READ_TIMEOUT_S = 2.5
_HANDSHAKE_ATTEMPTS = 3
_OPEN_ATTEMPTS = 3

#: Lower bound the firmware accepts for ``REGULATOR_SET``, in millivolts.
#: Below this and the on-board LDO won't regulate cleanly.
VOLTAGE_LIMIT_HARDWARE_MIN_MV: int = 800

#: Upper bound the PPK2 hardware can supply via the on-board regulator,
#: in millivolts. Wired to the LDO; this is a true hard ceiling. Any
#: [`Session.set_voltage_limit`][] call is itself clamped to this bound
#: — the user-set limit is purely a lower-the-ceiling knob.
VOLTAGE_LIMIT_HARDWARE_MAX_MV: int = 5000


class SessionError(Exception):
    """Base class for session lifecycle failures."""


class SerialIOError(SessionError):
    """Underlying serial I/O failed."""


class MetadataParseError(SessionError):
    """Metadata bytes arrived but didn't parse."""

    def __init__(self, cause: MetadataError) -> None:
        """Wrap the underlying [`ppk2.protocol.metadata.MetadataError`][] cause for diagnostics."""
        super().__init__(f"metadata parse failed: {cause}")
        self.cause = cause


class HandshakeFailed(SessionError):
    """The metadata recovery loop exhausted all attempts.

    ``attempts`` is the number tried; ``last`` is a human-readable
    diagnostic for the final failure (write failure, no END, parse error).
    """

    def __init__(self, attempts: int, last: str) -> None:
        """Build a HandshakeFailed error, recording the attempt count and last diagnostic."""
        super().__init__(f"metadata recovery failed after {attempts} attempts; last: {last}")
        self.attempts = attempts
        self.last = last


class Mode(IntEnum):
    """PPK2 measurement mode. Discriminant is the wire byte."""

    AMPERE = 0x01
    SOURCE = 0x02


class Session:
    """An open PPK2 session.

    Wraps the serial port plus the parsed per-device calibration. Use as
    a context manager (``with Session.open(port) as s: …``) so the
    teardown (stop streaming + open FET + close port) runs even on
    exception.

    Threading: one [`Session`][] per thread. The underlying serial
    port is not shareable by reference across threads.
    """

    def __init__(self, port: serial.Serial, coeffs: CalibrationCoefficients) -> None:
        """Wrap a pre-opened serial port and its parsed calibration.

        Most callers should use [`Session.open`][] instead, which runs
        the open + handshake. This constructor exists for tests that
        wire in a pre-built mock port + coefficients.

        The initial VDD setpoint is seeded from ``coeffs.vdd_mv`` — the
        value the firmware reported at metadata-read time, which
        survives across host disconnects. A PPK2 last left in source
        mode at 1800 mV starts the next session at 1800 mV; a subsequent
        [`set_source_voltage`][] overrides it. Matches the Nordic GUI.
        """
        self._port = port
        self._coeffs = coeffs
        self._vdd_mv = coeffs.vdd_mv
        self._spike_filter = SpikeFilter()
        self._voltage_limit_mv = VOLTAGE_LIMIT_HARDWARE_MAX_MV
        self._closed = False
        self._measuring = False

    # ── Construction ───────────────────────────────────────────────────

    @classmethod
    def open(cls, device: str) -> "Session":
        """Open ``device`` and run the recover-and-negotiate handshake.

        Up to 3 attempts, with 0.5 s / 1.0 s backoffs between them
        (no sleep after the final failure — 1.5 s total backoff).
        Designed to handle the macOS USB CDC wedge that sometimes
        follows a peer process's previous capture, especially if that
        capture sent ``RESET`` on close.
        """
        last_err: SessionError = SerialIOError("open: never attempted")
        for attempt in range(_OPEN_ATTEMPTS):
            try:
                port, coeffs = cls._try_open_once(device)
            except SessionError as exc:
                last_err = exc
                if attempt == _OPEN_ATTEMPTS - 1:
                    break
                # 0.5 s then 1.0 s — 1.5 s total backoff across 3 attempts.
                sleep(0.5 * (1 << attempt))
                continue
            else:
                return cls(port=port, coeffs=coeffs)
        raise last_err

    @staticmethod
    def _try_open_once(device: str) -> tuple[serial.Serial, CalibrationCoefficients]:
        """One open + handshake attempt. Caller retries on failure."""
        try:
            # exclusive=True (POSIX: flock LOCK_EX | LOCK_NB) makes
            # contention visible both ways: this open fails if any
            # lock-respecting process holds the port, and while the
            # session lives, lock-respecting openers fail against us.
            # Kernel-enforced exclusivity (the Nordic GUI's TIOCEXCL)
            # already rejects the open unconditionally.
            port = serial.Serial(
                device,
                baudrate=_BAUD_RATE,
                timeout=_READ_TIMEOUT_S,
                write_timeout=_READ_TIMEOUT_S,
                exclusive=True,
            )
        except serial.SerialException as exc:
            raise SerialIOError(f"serial open: {exc}") from exc
        sleep(_OPEN_SETTLE_S)
        _empty_serial(port)
        coeffs = _recover_and_negotiate(port)
        return port, coeffs

    # ── Context manager protocol ───────────────────────────────────────

    def __enter__(self) -> "Session":
        """Enter the with-block; the open + handshake already ran in [`open`][]."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Exit the with-block by running [`close`][]."""
        self.close()

    def close(self) -> None:
        """Tear down the session: stop streaming, best-effort FET-open, close the port.

        Idempotent. Errors during teardown are silenced — we deliberately
        do NOT send ``RESET`` because that triggers a ~200-500 ms USB CDC
        re-enumeration on macOS that frequently wedges the next session.

        The ``DEVICE_RUNNING_SET(off)`` here is best-effort only: it is
        sent right after ``AVERAGE_STOP``, and the firmware is known to
        silently drop FET toggles when no sample stream is active (see
        [`Opcode.DEVICE_RUNNING_SET`][ppk2.protocol.opcode.Opcode.DEVICE_RUNNING_SET]).
        Callers that must guarantee the FET opens should call
        [`power_off`][] while still measuring — the order
        [`capture`][] and ``ppk2 power`` use.
        """
        if self._closed:
            return
        self._closed = True
        with suppress(serial.SerialException):
            self._port.write(bytes([Opcode.AVERAGE_STOP.byte()]))
        with suppress(serial.SerialException):
            self._port.write(bytes([Opcode.DEVICE_RUNNING_SET.byte(), 0x00]))
        with suppress(serial.SerialException):
            self._port.close()

    # ── Accessors ──────────────────────────────────────────────────────

    def coefficients(self) -> CalibrationCoefficients:
        """Per-device calibration block read at session open."""
        return self._coeffs

    # ── Configuration ──────────────────────────────────────────────────

    def set_mode(self, mode: Mode) -> None:
        """Select the PPK2's measurement mode.

        The firmware accepts ``SET_POWER_MODE`` only while no sample
        stream is active. Call this BEFORE [`start_measuring`][].
        """
        self._write(bytes([Opcode.SET_POWER_MODE.byte(), int(mode)]))

    def set_source_voltage(self, mv: int) -> None:
        """Set the source-mode VDD setpoint in millivolts.

        Also feeds the calibration formula's VDD-dependent term in
        ammeter mode, where the setpoint is informational only.

        Clamped to ``[VOLTAGE_LIMIT_HARDWARE_MIN_MV,
        VOLTAGE_LIMIT_HARDWARE_MAX_MV]`` (800 mV to 5000 mV) — the
        firmware ignores values outside that band, so the host clamp
        gives the caller a defined behaviour.

        If the requested voltage exceeds the host-side ceiling set by
        [`set_voltage_limit`][], raises `ValueError` instead of
        silently truncating. The ceiling defaults to the hardware max,
        so this only kicks in when a caller has explicitly tightened it.

        Args:
            mv: Requested setpoint in millivolts.

        Raises:
            ValueError: If ``mv`` exceeds the configured ceiling.
            SerialIOError: If the underlying serial write fails.
        """
        clamped = max(VOLTAGE_LIMIT_HARDWARE_MIN_MV, min(VOLTAGE_LIMIT_HARDWARE_MAX_MV, mv))
        if clamped > self._voltage_limit_mv:
            raise ValueError(
                f"requested {mv} mV exceeds voltage limit "
                f"{self._voltage_limit_mv} mV — call set_voltage_limit "
                f"first if you want to raise the ceiling"
            )
        wire = bytes(
            [
                Opcode.REGULATOR_SET.byte(),
                (clamped >> 8) & 0xFF,
                clamped & 0xFF,
            ]
        )
        self._write(wire)
        self._vdd_mv = clamped

    def set_voltage_limit(self, mv: int) -> None:
        """Set the host-enforced maximum source voltage, in millivolts.

        Acts as a software safety interlock — any future
        [`set_source_voltage`][] call requesting a value above this
        limit raises `ValueError` rather than writing the wire
        frame. Designed to prevent fat-fingering a DUT-damaging
        voltage during interactive scripting.

        The limit is itself clamped to
        ``[VOLTAGE_LIMIT_HARDWARE_MIN_MV,
        VOLTAGE_LIMIT_HARDWARE_MAX_MV]`` so a caller can't accidentally
        raise it above what the on-board regulator can produce.

        If the new limit is lower than the currently-set VDD, the
        existing setpoint is NOT changed — the limit only constrains
        future writes. Call [`set_source_voltage`][] afterwards if you
        need to bring the present voltage down too.

        Mirrors the Nordic GUI's "Maximum supply voltage" knob under
        Advanced Configuration.

        Args:
            mv: New ceiling in millivolts. Will be clamped to the
                hardware-supported band.

        Raises:
            RuntimeError: If called after [`start_measuring`][] — the
                new ceiling could conflict with the present setpoint
                and we'd rather surface that explicitly than at the
                next user write. Same lifecycle guard as
                [`set_user_gain`][] and [`set_spike_filter`][].
        """
        if self._measuring:
            raise RuntimeError("set_voltage_limit must be called before start_measuring()")
        self._voltage_limit_mv = max(
            VOLTAGE_LIMIT_HARDWARE_MIN_MV,
            min(VOLTAGE_LIMIT_HARDWARE_MAX_MV, mv),
        )

    def voltage_limit(self) -> int:
        """Return the host-enforced maximum source voltage, in millivolts."""
        return self._voltage_limit_mv

    # ── Stream control ─────────────────────────────────────────────────

    def start_measuring(self) -> None:
        """Start the 100 kSPS sample stream and wait 200 ms for settle.

        The settle is load-bearing — a firmware quirk silently drops
        ``DEVICE_RUNNING_SET`` calls that arrive within ~150 ms after
        ``AVERAGE_START``.
        """
        self._write(bytes([Opcode.AVERAGE_START.byte()]))
        sleep(_START_MEASURING_SETTLE_S)
        self._measuring = True

    def stop_measuring(self) -> None:
        """Send ``AVERAGE_STOP``. Safe to call when no stream is active."""
        self._write(bytes([Opcode.AVERAGE_STOP.byte()]))

    # ── FET toggle ─────────────────────────────────────────────────────

    def power_on(self, latch_s: float = 1.0) -> None:
        """Close the DUT-power FET, draining the stream around the toggle.

        Requires [`start_measuring`][] to have run already — the
        firmware silently drops ``DEVICE_RUNNING_SET`` without an
        active stream.

        The drains are load-bearing: the PPK2 only latches the FET
        after the host has kept reading for a stretch. The pending
        backlog is drained first (~0.3 s) so the toggle lands on a
        live, caught-up stream; then the stream is drained for
        ``latch_s`` more.

        Args:
            latch_s: Post-toggle drain duration in seconds. The
                default (1.0) latches the FET before this call
                returns — right for one-shot power-on (``ppk2 power
                on``). Capture paths pass ``0.0`` and let the capture
                loop's own reads finish the latch, so t=0 in the
                trace ≈ FET-on and the DUT's boot inrush lands in the
                CSV; pair that with [`drop_pending_backlog`][] at
                capture-loop start.
        """
        self._drain_stream(_POWER_ON_PRE_DRAIN_S)
        self._write(bytes([Opcode.DEVICE_RUNNING_SET.byte(), 0x01]))
        self._drain_stream(latch_s)

    def power_off(self) -> None:
        """Open the DUT-power FET. Idempotent."""
        self._write(bytes([Opcode.DEVICE_RUNNING_SET.byte(), 0x00]))

    def drop_pending_backlog(self) -> int:
        """Discard whatever is sitting in the input buffer — one read, not a loop.

        Deliberately bounded to a single ``in_waiting``-sized read:
        once the stream is running it never goes empty, so a
        drain-until-empty loop would hang. Call once at capture-loop
        start (after ``power_on(latch_s=0.0)``) so the first parsed
        sample is ≈ now ≈ FET-on rather than the oldest byte the OS
        buffered during session setup.

        Returns:
            The number of bytes discarded.

        Raises:
            SerialIOError: If the underlying serial I/O fails.
        """
        try:
            waiting = self._port.in_waiting
            if waiting:
                self._port.read(waiting)
        except serial.SerialException as exc:
            raise SerialIOError(f"serial read: {exc}") from exc
        return waiting

    # ── User gain override ─────────────────────────────────────────────

    def set_user_gain(self, range_idx: int, gain: float) -> None:
        """Override the per-range user gain (UG) for this session.

        Applied host-side: the in-session [`CalibrationCoefficients`][]
        is rebuilt with the new ``ug[range_idx]``, and the next
        [`capture`][] builds its [`StreamParser`][] from the updated
        block. No wire write is issued — testing against current PPK2
        firmware shows it silently ignores ``SET_USER_GAINS`` (0x25),
        and the Nordic GUI's calibration likewise reads only its
        in-memory ``ug`` array, so the host-side rebuild is the only
        behaviour with any effect.

        Call **before** [`start_measuring`][]; the active capture's
        parser holds the coefficients it was built with. The override
        does not persist across [`close`][] — the next
        [`Session.open`][] re-reads the firmware's stored UG.

        Args:
            range_idx: 0..=4. Which of the five hardware shunt ranges
                the gain applies to.
            gain: User gain. Typically near 1.0.

        Raises:
            ValueError: If ``range_idx`` is outside 0..=4.
            RuntimeError: If called after [`start_measuring`][].
        """
        if self._measuring:
            raise RuntimeError(
                "set_user_gain must be called before start_measuring(); "
                "the active capture's StreamParser uses the coefficients "
                "captured at init time."
            )
        if not 0 <= range_idx <= 4:
            raise ValueError(f"range_idx must be 0..=4, got {range_idx}")
        # Host-side only: rebuild self._coeffs with the new ug[range_idx].
        # No wire write — see docstring; the firmware ignores 0x25.
        old_ug = self._coeffs.ug
        new_ug: RangeArray = (
            gain if range_idx == 0 else old_ug[0],
            gain if range_idx == 1 else old_ug[1],
            gain if range_idx == 2 else old_ug[2],
            gain if range_idx == 3 else old_ug[3],
            gain if range_idx == 4 else old_ug[4],
        )
        self._coeffs = replace(self._coeffs, ug=new_ug)

    # ── Spike-filter knobs ─────────────────────────────────────────────

    def set_spike_filter(
        self,
        *,
        samples: int | None = None,
        alpha: float | None = None,
        alpha5: float | None = None,
    ) -> None:
        """Tweak the post-range-change EMA spike filter.

        Keyword-only partial update — pass just the knob(s) you want to
        change; the rest keep their current values. Defaults are
        documented on [`ppk2.protocol.SpikeFilter`][].

        The filter is applied **host-side** inside
        [`ppk2.protocol.StreamParser`][]. There is no corresponding wire
        opcode — the Nordic GUI applies the same knobs host-side too.
        The next [`Session.capture`][ppk2.client.session.Session.capture] constructs its
        [`StreamParser`][] with the updated filter; the active
        capture's parser captures the filter by value at construction
        time, so a mid-capture change can't take effect — we raise
        rather than silently no-op.

        The override **does not persist** across [`close`][]. The next
        [`Session.open`][] starts a fresh session with defaults.

        Args:
            samples: New post-range-change smoothing window length, in
                samples. ``None`` leaves the existing value.
            alpha: New EMA coefficient for ranges 0..=3. ``None`` leaves
                the existing value.
            alpha5: New EMA coefficient for range 4. ``None`` leaves the
                existing value.

        Raises:
            ValueError: If any new knob is outside its valid range — see
                [`ppk2.protocol.SpikeFilter`][] for the constraints.
            RuntimeError: If called after [`start_measuring`][].
        """
        if self._measuring:
            raise RuntimeError(
                "set_spike_filter must be called before start_measuring(); "
                "the active capture's StreamParser was built with the "
                "previous filter and can't switch mid-stream."
            )
        current = self._spike_filter
        self._spike_filter = SpikeFilter(
            samples=current.samples if samples is None else samples,
            alpha=current.alpha if alpha is None else alpha,
            alpha5=current.alpha5 if alpha5 is None else alpha5,
        )

    def spike_filter(self) -> SpikeFilter:
        """Return the spike-filter knobs the next capture loop will use.

        The active capture's parser captured them at construction time
        — see [`Session.capture`][ppk2.client.session.Session.capture].
        """
        return self._spike_filter

    # ── Capture loop ───────────────────────────────────────────────────

    def capture(
        self,
        emit: Callable[[Sample], bool],
        on_dataloss: Callable[[int], None] | None = None,
    ) -> None:
        """Read bytes, parse them, invoke ``emit`` once per sample.

        ``emit`` returns ``True`` to keep going, ``False`` to stop. The
        method returns when the caller stops, or never (open-ended).

        Args:
            emit: Callback invoked per [`ppk2.protocol.Sample`][].
                Return ``False`` to break the capture loop.
            on_dataloss: Optional callback invoked when the stream
                parser's cumulative data-loss count grows during a
                ``push_bytes`` iteration. Receives the post-event total
                (monotonically non-decreasing across the capture's
                lifetime). Use to surface a stderr warning, increment a
                metric, etc. Called at most once per ``push_bytes``
                invocation regardless of how many NaN placeholders the
                parser emitted in that batch.
        """
        parser = StreamParser(self._coeffs, self._vdd_mv, self._spike_filter)
        scratch = bytearray(4096)
        stop = False

        def collect(sample: Sample) -> None:
            nonlocal stop
            if not emit(sample):
                stop = True

        while not stop:
            n = self._read_into(scratch)
            if n == 0:
                continue
            before = parser.dataloss_total
            parser.push_bytes(bytes(scratch[:n]), collect)
            if on_dataloss is not None and parser.dataloss_total > before:
                on_dataloss(parser.dataloss_total)

    # ── Internals ──────────────────────────────────────────────────────

    def _drain_stream(self, seconds: float) -> None:
        """Read and discard stream bytes for ``seconds``, keeping up with the rate."""
        deadline = monotonic() + seconds
        scratch = bytearray(4096)
        while monotonic() < deadline:
            self._read_into(scratch)

    def _write(self, payload: bytes) -> None:
        try:
            self._port.write(payload)
        except serial.SerialException as exc:
            raise SerialIOError(f"serial write: {exc}") from exc

    def _read_into(self, buf: bytearray) -> int:
        """Read up to ``len(buf)`` bytes; return the actual count.

        Treats timeouts as "no bytes yet" (returns 0) so the caller's
        capture loop can check its own stop condition.
        """
        try:
            chunk = self._port.read(len(buf))
        except serial.SerialException as exc:
            raise SerialIOError(f"serial read: {exc}") from exc
        n = len(chunk)
        if n:
            buf[:n] = chunk
        return n


# ─── module-private helpers ────────────────────────────────────────────


def _empty_serial(port: serial.Serial) -> None:
    """Drain whatever the firmware was still emitting, up to ~1 s."""
    deadline = monotonic() + 1.0
    while monotonic() < deadline:
        try:
            waiting = port.in_waiting
        except (serial.SerialException, OSError):
            return
        if waiting == 0:
            return
        try:
            port.read(waiting)
        except serial.SerialException:
            return


class BytesReader(Protocol):
    """Minimal ``.read(n) -> bytes`` shape used by [`read_until_end`][].

    pyserial's ``Serial.read`` and tests' in-memory fakes both match
    this. Defined as a Protocol so callers don't have to inherit
    anything to be accepted.
    """

    def read(self, n: int, /) -> bytes:
        """Read up to ``n`` bytes; return ``b""`` if none are ready."""
        ...


def read_until_end(reader: BytesReader, total_timeout_s: float) -> bytes:
    """Accumulating read until the buffer contains ``b"END"`` or timeout.

    Tolerates chunked I/O — covers the case where the metadata response
    arrives in two pyserial reads (header then tail). Module-public so
    tests can drive the chunked-accumulation logic with an in-memory
    fake; intentionally absent from ``ppk2.client.__all__`` because it's
    an internal composition primitive, not part of the documented API.
    """
    deadline = monotonic() + total_timeout_s
    buf = bytearray()

    while monotonic() < deadline:
        chunk = reader.read(512)
        if not chunk:
            sleep(0.02)
            continue
        buf.extend(chunk)
        if b"END" in buf:
            return bytes(buf)

    raise TimeoutError(f"no END within {total_timeout_s}s; buffered {len(buf)} bytes")


def _recover_and_negotiate(port: serial.Serial) -> CalibrationCoefficients:
    """Stop any prior stream, (on retry) reset, read metadata, parse.

    Up to 3 attempts. Writes that fail are captured into ``last_failure``
    rather than silently dropped — under a macOS CDC wedge every write
    errors out, and burying that behind a downstream parse failure
    would mask the real cause.
    """
    last_failure = "(no attempts made)"

    for attempt in range(_HANDSHAKE_ATTEMPTS):
        # Flush any prior streaming.
        try:
            port.write(bytes([Opcode.AVERAGE_STOP.byte()]))
        except serial.SerialException as exc:
            last_failure = f"write AVERAGE_STOP: {exc}"
            continue
        sleep(0.1)

        # RESET on retry attempts only — it costs a USB CDC re-enum on
        # macOS, so we want a clean attempt first.
        if attempt > 0:
            try:
                port.write(bytes([Opcode.RESET.byte()]))
            except serial.SerialException as exc:
                last_failure = f"write RESET: {exc}"
                continue
            sleep(0.3)

        # Clear pyserial's input buffer + drain whatever the firmware
        # was still emitting.
        with suppress(serial.SerialException):
            port.reset_input_buffer()
        _empty_serial(port)

        # Request metadata + accumulate until END.
        try:
            port.write(bytes([Opcode.GET_METADATA.byte()]))
        except serial.SerialException as exc:
            last_failure = f"write GET_META_DATA: {exc}"
            continue

        # pyserial's Serial already matches the BytesReader shape
        # (read(n) -> b"" on timeout).
        try:
            buf = read_until_end(port, _METADATA_READ_TIMEOUT_S)
        except (TimeoutError, OSError) as exc:
            last_failure = f"read metadata: {exc}"
            continue

        try:
            return parse_metadata(buf)
        except MetadataError as exc:
            last_failure = f"parse_metadata: {exc!r}"
            continue

    raise HandshakeFailed(_HANDSHAKE_ATTEMPTS, last_failure)
