"""PPK2 session lifecycle: open, configure, stream, tear down.

``Session`` is a context manager; leaving the block stops the stream,
switches the DUT off and closes the port.

>>> with Session.open(port) as s:
...     s.set_mode(Mode.AMPERE)
...     s.set_source_voltage(3300)
...     s.start_measuring()
...     s.power_on()
...     s.capture(on_sample)  # until on_sample returns False
"""

import warnings
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
_START_BUSY_S = 0.35  # the PPK2 holds commands for 0.31 s after AVERAGE_START
_STREAM_BYTES_PER_S = 400_000  # 100,000 samples of 4 bytes
_CAUGHT_UP_BYTES = 4_000  # within 10 ms of the stream: caught up
_CATCH_UP_CAP_S = 1.5  # how long to try, at most
_METADATA_READ_TIMEOUT_S = 2.5
_QUIET_S = 0.05  # no byte for this long: the stream has ended
_QUIET_CAP_S = 0.5  # how long to wait for that, at most
_HANDSHAKE_ATTEMPTS = 3
_OPEN_ATTEMPTS = 3

#: Lowest ``REGULATOR_SET`` value the firmware accepts, in millivolts.
#: Below it the on-board LDO does not regulate cleanly.
VOLTAGE_LIMIT_HARDWARE_MIN_MV: int = 800

#: Highest voltage the on-board regulator can supply, in millivolts: a
#: hard ceiling. ``Session.set_voltage_limit`` can only lower it.
VOLTAGE_LIMIT_HARDWARE_MAX_MV: int = 5000

#: The user gains Nordic's app accepts, per range.
USER_GAIN_MIN: float = 0.9
USER_GAIN_MAX: float = 1.1


class SessionError(Exception):
    """Base class for session lifecycle failures."""


class SerialIOError(SessionError):
    """Underlying serial I/O failed."""


class HandshakeFailed(SessionError):
    """The metadata handshake ran out of attempts.

    ``attempts`` is how many were made; ``last`` describes the final
    failure (write error, no END, parse error).
    """

    def __init__(self, attempts: int, last: str) -> None:
        super().__init__(f"metadata recovery failed after {attempts} attempts; last: {last}")
        self.attempts = attempts
        self.last = last


class Mode(IntEnum):
    """PPK2 measurement mode; the value is the wire byte.

    ``AMPERE`` is the Ampere meter mode of Nordic's app: the DUT has its
    own supply and the PPK2 sits in series. ``SOURCE`` is its Source
    meter mode: the PPK2 supplies the DUT.
    """

    AMPERE = 0x01
    SOURCE = 0x02


class Session:
    """An open PPK2 session: the serial port plus the device's calibration.

    Use it as a context manager (``with Session.open(port) as s:``) so
    the teardown runs even on an exception.

    One ``Session`` per thread: the serial port underneath is not safe
    to share.
    """

    def __init__(self, port: serial.Serial, coeffs: CalibrationCoefficients) -> None:
        """Wrap an already-open port and its parsed calibration.

        Prefer ``Session.open``, which opens the port and runs the
        handshake.

        The supply voltage starts at ``coeffs.vdd_mv``, the value the
        firmware reported and keeps across host disconnects: a PPK2
        left at 1800 mV starts the next session at 1800 mV until
        ``set_source_voltage`` says otherwise. Same as Nordic's app.
        """
        self._port = port
        if not all(USER_GAIN_MIN <= g <= USER_GAIN_MAX for g in coeffs.ug):
            # As Nordic's app does when it connects.
            warnings.warn(
                f"the PPK2 reports a user gain outside {USER_GAIN_MIN} to "
                f"{USER_GAIN_MAX} ({coeffs.ug}); all five are taken as 1.0",
                RuntimeWarning,
                stacklevel=2,
            )
            coeffs = replace(coeffs, ug=(1.0, 1.0, 1.0, 1.0, 1.0))
        self._coeffs = coeffs
        self._vdd_mv = coeffs.vdd_mv
        self._spike_filter = SpikeFilter()
        self._voltage_limit_mv = VOLTAGE_LIMIT_HARDWARE_MAX_MV
        self._closed = False
        self._measuring = False
        self._stream_started_at = 0.0
        self._stream_bytes = 0  # read since start_measuring

    # ── Construction ───────────────────────────────────────────────────

    @classmethod
    def open(cls, device: str) -> "Session":
        """Open ``device`` and run the metadata handshake.

        Up to 3 attempts, 0.5 s then 1.0 s apart. The retries are for
        the macOS USB CDC wedge that can follow another process's
        capture, especially one that sent ``RESET`` on close.
        """
        last_err: SessionError = SerialIOError("open: never attempted")
        for attempt in range(_OPEN_ATTEMPTS):
            try:
                port, coeffs = cls._try_open_once(device)
            except SessionError as exc:
                last_err = exc
                if attempt == _OPEN_ATTEMPTS - 1:
                    break
                # 0.5 s then 1.0 s: 1.5 s total backoff across 3 attempts.
                sleep(0.5 * (1 << attempt))
                continue
            else:
                return cls(port=port, coeffs=coeffs)
        raise last_err

    @staticmethod
    def _try_open_once(device: str) -> tuple[serial.Serial, CalibrationCoefficients]:
        """One open + handshake attempt."""
        try:
            # exclusive=True: the open fails while another program
            # holds the port, and others fail while this session lives.
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
        try:
            _empty_serial(port)
            coeffs = _recover_and_negotiate(port)
        except BaseException:
            # Left open, the port would keep its lock and fail the next attempt.
            with suppress(Exception):
                port.close()
            raise
        return port, coeffs

    # ── Context manager protocol ───────────────────────────────────────

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        """Stop the stream, cut power to the DUT, wait for the stream to end, close the port.

        Idempotent; errors are swallowed. No ``RESET`` is sent: on macOS it
        triggers a USB re-enumeration (~200-500 ms) that often wedges the next
        session.

        The port is not closed while samples still arrive. Closed right
        after ``AVERAGE_STOP``, the PPK2 can miss the command and keep
        streaming, and what was in flight goes to whoever opens the port
        next: a client that asks for the metadata first, like Nordic's
        own tools, then gets no usable answer.

        DUT power does not outlive the session: the PPK2 cuts it by itself
        when the port closes (it follows the DTR line), so this holds even
        when the process is killed and this method never runs.
        """
        if self._closed:
            return
        self._closed = True
        with suppress(serial.SerialException):
            self._port.write(bytes([Opcode.AVERAGE_STOP.byte()]))
        with suppress(serial.SerialException):
            self._port.write(bytes([Opcode.DEVICE_RUNNING_SET.byte(), 0x00]))
        self._wait_for_quiet()
        with suppress(serial.SerialException):
            self._port.close()

    # ── Accessors ──────────────────────────────────────────────────────

    def coefficients(self) -> CalibrationCoefficients:
        """Per-device calibration read at session open."""
        return self._coeffs

    # ── Configuration ──────────────────────────────────────────────────

    def set_mode(self, mode: Mode) -> None:
        """Select the measurement mode.

        Call it before ``start_measuring``. A change sent during a
        stream was once reported as ignored; on the unit tested it was
        applied, but nothing here relies on it.
        """
        self._write(bytes([Opcode.SET_POWER_MODE.byte(), int(mode)]))

    def set_source_voltage(self, mv: int) -> None:
        """Set the supply voltage in millivolts.

        In Source meter mode this is what the PPK2 outputs. In Ampere
        meter mode the regulator is inactive, but the value still feeds
        the calibration: set it to the DUT's real supply voltage.

        Values outside 800-5000 mV are clamped; the firmware ignores
        them otherwise.

        Raises:
            ValueError: If ``mv`` exceeds the cap set with
                ``set_voltage_limit``.
            SerialIOError: If the serial write fails.
        """
        clamped = max(VOLTAGE_LIMIT_HARDWARE_MIN_MV, min(VOLTAGE_LIMIT_HARDWARE_MAX_MV, mv))
        if clamped > self._voltage_limit_mv:
            raise ValueError(
                f"requested {mv} mV exceeds voltage limit "
                f"{self._voltage_limit_mv} mV: call set_voltage_limit "
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
        """Cap what ``set_source_voltage`` will accept, in millivolts.

        A host-side guard against typing a DUT-damaging voltage, like
        the app's voltage limit ("Set max supply voltage to"). The cap
        is itself clamped to 800-5000 mV, and it does not change a
        supply voltage already above it.

        Raises:
            RuntimeError: If called while a stream runs, between
                ``start_measuring`` and ``stop_measuring``.
        """
        if self._measuring:
            raise RuntimeError("set_voltage_limit must be called before start_measuring()")
        self._voltage_limit_mv = max(
            VOLTAGE_LIMIT_HARDWARE_MIN_MV,
            min(VOLTAGE_LIMIT_HARDWARE_MAX_MV, mv),
        )

    def voltage_limit(self) -> int:
        """The cap set by ``set_voltage_limit``, in millivolts."""
        return self._voltage_limit_mv

    # ── Stream control ─────────────────────────────────────────────────

    def start_measuring(self) -> None:
        """Start the 100 kSPS sample stream."""
        self._write(bytes([Opcode.AVERAGE_START.byte()]))
        self._stream_started_at = monotonic()
        self._stream_bytes = 0
        self._measuring = True

    def stop_measuring(self) -> None:
        """Send ``AVERAGE_STOP`` and read the stream out to its end.

        Left unread, the end of the stream would lead the next one: a
        few milliseconds of samples from before the stop. Safe to call
        when no stream is active.
        """
        self._write(bytes([Opcode.AVERAGE_STOP.byte()]))
        self._wait_for_quiet()
        self._measuring = False

    # ── DUT power ──────────────────────────────────────────────────────

    def power_on(self) -> None:
        """Switch power to the DUT on, as the app's "Enable power output" does.

        The power comes up about 1 ms after the command. With a stream
        running, the stream is first read until the host has caught up
        with it, which takes until about 0.9 s after ``start_measuring``.
        The samples read after this call are then from the switch on, to
        within about 10 ms, so a capture that follows has the boot in it
        (the protocol page, Known caveats).
        """
        self._catch_up()
        self._write(bytes([Opcode.DEVICE_RUNNING_SET.byte(), 0x01]))

    def power_off(self) -> None:
        """Switch power to the DUT off. Idempotent."""
        self._write(bytes([Opcode.DEVICE_RUNNING_SET.byte(), 0x00]))

    def drop_pending_backlog(self) -> int:
        """Discard what the OS reports as waiting; return the byte count.

        One read, not a loop: a running stream never goes empty, so
        draining until empty would hang. It does not bring the reads up
        to the present: on macOS ``in_waiting`` reports about 1 kB while
        some 40 kB are queued (the protocol page, Known caveats).

        Raises:
            SerialIOError: If the serial read fails.
        """
        try:
            waiting = self._port.in_waiting
            if waiting:
                self._stream_bytes += len(self._port.read(waiting))
        except serial.SerialException as exc:
            raise SerialIOError(f"serial read: {exc}") from exc
        return waiting

    # ── User gain override ─────────────────────────────────────────────

    def set_user_gain(self, range_idx: int, gain: float) -> None:
        """Override the user gain of one range for this session.

        Host-side only: the calibration used by the next ``capture`` is
        rebuilt with the new gain and nothing is sent. Current firmware
        ignores ``SET_USER_GAINS``, and Nordic's app applies the gain
        host-side too. The override is gone at ``close``.

        Args:
            range_idx: Which of the five measurement ranges, 0-4. The
                app numbers them 1 to 5.
            gain: The gain, from 0.9 to 1.1 as in the app.

        Raises:
            ValueError: If ``range_idx`` is not 0-4, or ``gain`` is not
                from 0.9 to 1.1.
            RuntimeError: If called while a stream runs, between
                ``start_measuring`` and ``stop_measuring``.
        """
        if self._measuring:
            raise RuntimeError(
                "set_user_gain must be called before start_measuring(); "
                "the active capture's StreamParser uses the coefficients "
                "captured at init time."
            )
        if not 0 <= range_idx <= 4:
            raise ValueError(f"range_idx must be 0 to 4, got {range_idx}")
        if not USER_GAIN_MIN <= gain <= USER_GAIN_MAX:
            raise ValueError(f"gain must be from {USER_GAIN_MIN} to {USER_GAIN_MAX}, got {gain}")
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
        """Change spike-filter knobs; the ones not passed keep their value.

        Host-side, like Nordic's app: the next ``capture`` builds its
        parser with these. See ``SpikeFilter`` for what each knob does
        and its limits. The change is gone at ``close``.

        Raises:
            ValueError: If a knob is out of range.
            RuntimeError: If called while a stream runs, between
                ``start_measuring`` and ``stop_measuring``.
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
        """The spike-filter knobs the next ``capture`` will use."""
        return self._spike_filter

    # ── Capture loop ───────────────────────────────────────────────────

    def capture(
        self,
        emit: Callable[[Sample], bool],
        on_dataloss: Callable[[int], None] | None = None,
        keep_going: Callable[[], bool] | None = None,
    ) -> None:
        """Read the stream and call ``emit`` per sample until it returns ``False``.

        Args:
            emit: Called with each ``Sample``; return ``False`` to stop.
                It is not called again after that.
            on_dataloss: Called with the running total of lost samples
                whenever a read adds to it (at most once per read).
            keep_going: Called when a read times out with no data;
                return ``False`` to stop. Without it, a PPK2 that sends
                nothing keeps ``capture`` waiting for ever, since
                ``emit`` is never called.
        """
        parser = StreamParser(self._coeffs, self._vdd_mv, self._spike_filter)
        scratch = bytearray(4096)
        stop = False

        def collect(sample: Sample) -> None:
            nonlocal stop
            # The rest of a read is dropped once emit has said stop.
            if not stop and not emit(sample):
                stop = True

        while not stop:
            n = self._read_into(scratch)
            if n == 0:
                if keep_going is not None and not keep_going():
                    return
                continue
            before = parser.dataloss_total
            parser.push_bytes(bytes(scratch[:n]), collect)
            if on_dataloss is not None and parser.dataloss_total > before:
                on_dataloss(parser.dataloss_total)

    # ── Internals ──────────────────────────────────────────────────────

    def _catch_up(self) -> None:
        """Read and discard until the reads have caught up with the stream.

        For 0.31 s after ``AVERAGE_START`` the PPK2 sends slowly and
        holds any command it receives, and the host is level with the
        stream only after about 0.9 s (measured on macOS). Caught up
        means: past that first stretch, and as many bytes read as the
        PPK2 has produced since ``start_measuring``, to within 10 ms.
        Gives up after ``_CATCH_UP_CAP_S``. Does nothing without a
        stream.
        """
        if not self._measuring:
            return
        deadline = monotonic() + _CATCH_UP_CAP_S
        scratch = bytearray(4096)
        while (now := monotonic()) < deadline:
            elapsed = now - self._stream_started_at
            behind = elapsed * _STREAM_BYTES_PER_S - self._stream_bytes
            if elapsed >= _START_BUSY_S and behind <= _CAUGHT_UP_BYTES:
                return
            self._read_into(scratch)

    def _wait_for_quiet(self) -> None:
        """Read and discard until no byte arrives for ``_QUIET_S``.

        Gives up after ``_QUIET_CAP_S``. Best effort: the port may
        already be gone.
        """
        deadline = monotonic() + _QUIET_CAP_S
        with suppress(Exception):
            read_timeout = self._port.timeout
            self._port.timeout = _QUIET_S
            try:
                while monotonic() < deadline and self._port.read(4096):
                    pass
            finally:
                self._port.timeout = read_timeout

    def _write(self, payload: bytes) -> None:
        try:
            self._port.write(payload)
        except serial.SerialException as exc:
            raise SerialIOError(f"serial write: {exc}") from exc

    def _read_into(self, buf: bytearray) -> int:
        """Read up to ``len(buf)`` bytes into ``buf``; return the count, 0 on timeout."""
        try:
            chunk = self._port.read(len(buf))
        except serial.SerialException as exc:
            raise SerialIOError(f"serial read: {exc}") from exc
        n = len(chunk)
        if n:
            buf[:n] = chunk
            self._stream_bytes += n
        return n


# ─── module-private helpers ────────────────────────────────────────────


def flush_input(port: serial.Serial) -> None:
    """Discard buffered input, best effort.

    On a port that has just dropped off USB (the device re-enumerates
    after a ``RESET``), pyserial lets a bare ``termios.error`` through:
    neither ``SerialException`` nor ``OSError``. The next write or read
    reports the dead port properly.
    """
    with suppress(Exception):
        port.reset_input_buffer()


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
    """Anything with ``read(n) -> bytes``: pyserial's ``Serial``, or a test fake."""

    def read(self, n: int, /) -> bytes:
        """Read up to ``n`` bytes; return ``b""`` if none are ready."""
        ...


def read_until_end(reader: BytesReader, total_timeout_s: float) -> bytes:
    """Read until the data contains ``b"END"``, or raise ``TimeoutError``.

    The metadata response can arrive split across several reads.
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
    """Stop any stream, reset on retries, read and parse the metadata.

    Up to 3 attempts. A failed write is recorded as the failure instead
    of being skipped: under a macOS CDC wedge every write errors out,
    and reporting a later parse failure would hide the real cause.
    """
    last_failure = "(no attempts made)"

    for attempt in range(_HANDSHAKE_ATTEMPTS):
        # In case a stream was left running.
        try:
            port.write(bytes([Opcode.AVERAGE_STOP.byte()]))
        except serial.SerialException as exc:
            last_failure = f"write AVERAGE_STOP: {exc}"
            continue
        sleep(0.1)

        # RESET on retries only: it makes the PPK2 drop off USB.
        if attempt > 0:
            try:
                port.write(bytes([Opcode.RESET.byte()]))
            except serial.SerialException as exc:
                last_failure = f"write RESET: {exc}"
                continue
            sleep(0.3)

        # Discard what was still arriving.
        flush_input(port)
        _empty_serial(port)

        try:
            port.write(bytes([Opcode.GET_METADATA.byte()]))
        except serial.SerialException as exc:
            last_failure = f"write GET_META_DATA: {exc}"
            continue

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
