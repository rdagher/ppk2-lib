"""PPK2 port discovery — dual-VCOM-aware enumeration + active data-port probe.

Each PPK2 surfaces as two USB CDC interfaces ("VCOMs") that carry
identical USB descriptors; only one of them — the data port — answers
the wire protocol. Strategy:

1. List all serial ports via ``serial.tools.list_ports.comports``.
2. Filter to PPK2 interfaces by USB VID/PID (Nordic ``0x1915`` /
   ``0xC00A``) — see ``looks_like_ppk2``.
3. Group by USB serial number.
4. If more than one physical PPK2 is present, the caller must
   disambiguate via [`find_ppk2_by_serial`][].
5. Within the chosen device's group, identify the data port by
   **active probe**, lex-lowest candidate first (the usual hit): open
   the port, quiesce any running stream (``AVERAGE_STOP``), request
   metadata (``GET_METADATA``), and wait for the ``END`` terminator.
   Only the data port answers; the secondary VCOM opens but stays
   silent; a port held by another process (typically the nRF Connect
   Power Profiler GUI) fails to open at all. The probe runs *inside*
   the discovery retry loop, so a half-enumerated device is re-probed
   on the next poll tick instead of failing discovery outright.
6. When the quick pass finds no data port, escalate once with the
   session-style **recovery probe** (``RESET`` after the stop, the
   session's metadata budget). For a window after any session closes,
   the firmware stops answering ``GET_METADATA`` until reset — without
   the escalation the quick probe misclassifies the data port as idle.
"""

from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Literal

import serial
import serial.tools.list_ports

from ppk2.client.session import read_until_end
from ppk2.protocol import MetadataError, Opcode, parse_metadata

#: Default polling budget for [`find_ppk2`][]. Covers the ~200-500 ms
#: USB CDC re-enumeration that follows a teardown ``RESET`` on macOS so
#: back-to-back invocations don't race the re-enum.
DEFAULT_DISCOVERY_TIMEOUT_S = 3.0

#: Probe classification for one VCOM path: only the data interface
#: answers ``GET_METADATA``; the secondary VCOM opens but stays silent;
#: a port held by another process won't open at all.
PortStatus = Literal["data", "idle", "busy"]

#: Signature of a port-probe function — [`probe_port`][] or a test double.
ProbeFn = Callable[[str], PortStatus]


@dataclass(frozen=True)
class PortInfo:
    """A single PPK2 candidate enumerated on the host bus.

    Attributes:
        device: Filesystem path or COM name the OS exposes
            (e.g. ``/dev/cu.usbmodemA1B2C3D4E5F62`` on macOS,
            ``COM7`` on Windows).
        usb_serial: USB serial number assigned at manufacture
            (used as the stable handle when multiple PPK2s are
            plugged in).
    """

    device: str
    usb_serial: str


@dataclass(frozen=True)
class Ppk2Listing:
    """One connected PPK2 with per-VCOM probe statuses, for ``ppk2 list``.

    Attributes:
        usb_serial: USB serial number of the physical device.
        ports: Both VCOM paths, sorted lexicographically.
        data_port: The path that answered the metadata probe, or
            ``None`` if no candidate answered (typically because
            another process holds the data port).
        statuses: Per-path probe classification. Paths that were not
            probed because an earlier candidate already answered are
            reported ``"idle"``.
    """

    usb_serial: str
    ports: tuple[str, ...]
    data_port: str | None
    statuses: dict[str, PortStatus]


class DiscoveryError(Exception):
    """Base class for port discovery failures."""


class NotFound(DiscoveryError):
    """No PPK2 interface (USB VID/PID ``0x1915:0xC00A``) on the bus."""

    def __init__(self) -> None:
        """Build a NotFound error carrying the standard 'plug one in' diagnostic."""
        super().__init__("no PPK2 found (USB 1915:C00A) — plug one in / check the connection")


class Ambiguous(DiscoveryError):
    """More than one physical PPK2 is on the bus.

    ``count`` is the number of distinct USB serial numbers seen. The
    caller must pass the desired device's serial to
    [`find_ppk2_by_serial`][].
    """

    def __init__(self, count: int) -> None:
        """Build an Ambiguous error tagged with how many distinct PPK2s were seen."""
        super().__init__(
            f"{count} physical PPK2 devices found; pass --serial <usb-serial> to pick one"
        )
        self.count = count


class DataPortNotFound(DiscoveryError):
    """A PPK2 was enumerated but no VCOM answered the metadata probe.

    ``paths`` carries the candidate device paths that were probed.
    The usual cause is another process holding the data port open —
    the nRF Connect Power Profiler GUI keeps it held while running.
    """

    def __init__(self, paths: tuple[str, ...]) -> None:
        """Build the error, listing the probed candidate paths."""
        super().__init__(
            f"could not identify the PPK2 data port — none of {list(paths)} answered "
            "GET_METADATA; close the nRF Connect Power Profiler if it is open, "
            "or pass --port to select the port explicitly"
        )
        self.paths = paths


def find_ppk2(
    *,
    timeout_s: float = DEFAULT_DISCOVERY_TIMEOUT_S,
    probe: ProbeFn | None = None,
) -> PortInfo:
    """Locate the single PPK2 on the bus and return its probed data port.

    Polls for up to ``timeout_s`` seconds so back-to-back invocations
    can ride out the USB CDC re-enumeration after a teardown. The
    data-port probe runs on every poll tick, so a device that
    enumerated but hasn't finished coming up is retried rather than
    misclassified.

    Args:
        timeout_s: Polling budget in seconds. Set to 0 for a single
            enumeration + probe pass.
        probe: Port-probe override for tests. ``None`` uses the real
            serial probe ([`probe_port`][]).

    Returns:
        [`PortInfo`][] for the matched device, with ``device`` set to
        the VCOM that answered the metadata probe.

    Raises:
        NotFound: No PPK2-shaped device on the bus.
        Ambiguous: More than one physical PPK2 (raised immediately;
            polling won't help).
        DataPortNotFound: The device enumerated but no VCOM answered
            the probe within the budget.
    """
    return _poll_until_found(timeout_s, find_group_in, probe)


def find_ppk2_by_serial(
    usb_serial: str,
    *,
    timeout_s: float = DEFAULT_DISCOVERY_TIMEOUT_S,
    probe: ProbeFn | None = None,
) -> PortInfo:
    """Return the PPK2 whose USB serial matches ``usb_serial``.

    Substring matching is **not** supported; the serial must be an
    exact match to one enumerated by the OS. The data port is
    identified by active probe, same as [`find_ppk2`][].
    """
    return _poll_until_found(
        timeout_s,
        lambda ports: find_group_in_by_serial(ports, usb_serial),
        probe,
    )


def list_ppk2s(*, probe: ProbeFn | None = None) -> list[Ppk2Listing]:
    """Enumerate connected PPK2s with each VCOM's probe status.

    Backs the ``ppk2 list`` subcommand. Probes each device's VCOMs
    lex-lowest first and stops at the first data port — the remaining
    VCOMs are then idle by definition and are marked without a probe,
    keeping the common case to a single port open. When no candidate
    answers, every VCOM is probed so the statuses separate ``busy``
    (held by another process) from ``idle`` (silent) — the diagnostic
    for a failed discovery.

    Args:
        probe: Port-probe override for tests. ``None`` uses the real
            serial probe ([`probe_port`][]) with recovery escalation.
    """
    quick, recover = resolve_probes(probe)
    return build_listings(enumerate_ports(), quick, recover)


# ─── composition primitives ────────────────────────────────────────────
#
# Module-public but deliberately excluded from `__all__` — these are the
# pure-logic building blocks that the polling wrappers above call into.
# Exposed so tests can drive the dual-VCOM cases without spinning up
# pyserial; documented as "subject to change" for external consumers.


#: Nordic Semiconductor's USB vendor ID.
PPK2_VID: int = 0x1915

#: PPK2's USB product ID.
PPK2_PID: int = 0xC00A


@dataclass(frozen=True)
class RawPort:
    """Minimal view of a `serial.tools.list_ports_common.ListPortInfo` row.

    Carries the fields [`looks_like_ppk2`][] needs (USB VID/PID plus
    the serial number used for dual-VCOM grouping) so tests can
    synthesise port lists without depending on pyserial's structure.
    """

    device: str
    vid: int | None
    pid: int | None
    serial_number: str | None


def enumerate_ports() -> list[RawPort]:
    """Snapshot the current set of serial ports as [`RawPort`][] rows."""
    out: list[RawPort] = []
    for port in serial.tools.list_ports.comports():
        out.append(
            RawPort(
                device=port.device,
                vid=port.vid,
                pid=port.pid,
                serial_number=port.serial_number,
            )
        )
    return out


def looks_like_ppk2(port: RawPort) -> bool:
    """``True`` iff the port matches the PPK2 USB VID/PID.

    Filters on Nordic's USB vendor ID (``0x1915``) plus PPK2's product
    ID (``0xC00A``). Matches the Nordic GUI's selector — more reliable
    than matching on OS-reported product strings, which can be empty
    on Windows and vary between firmware revisions on Linux. Both CDC
    interfaces of a single PPK2 carry the same VID/PID, so this filter
    answers "is this a PPK2 interface?" but does not pick the data
    port — that's the active probe's job ([`probe_port`][]).
    """
    return port.vid == PPK2_VID and port.pid == PPK2_PID


def group_ppk2s(ports: list[RawPort]) -> dict[str, list[str]]:
    """Group PPK2 candidates by USB serial number; drop entries with no serial."""
    by_serial: dict[str, list[str]] = defaultdict(list)
    for port in ports:
        if not looks_like_ppk2(port):
            continue
        if port.serial_number is None:
            continue
        by_serial[port.serial_number].append(port.device)
    return dict(by_serial)


def lex_lowest(names: list[str]) -> str:
    """Pick the probe-first (and probe-less fallback) path within a VCOM group.

    Both interfaces share VID/PID, USB serial, manufacturer, and product
    strings; pyserial doesn't expose the USB interface descriptor that
    would distinguish them. Empirically the lower-numbered device path
    is the 100 kSPS data port on every bench observation so far, which
    makes it the right first candidate to probe — but the probe's
    answer, not this heuristic, is what discovery trusts.
    """
    return min(names)


def find_group_in(ports: list[RawPort]) -> tuple[str, tuple[str, ...]]:
    """Pick the single PPK2's ``(usb_serial, sorted VCOM paths)`` from ``ports``.

    Raises:
        NotFound: No PPK2-shaped device in ``ports``.
        Ambiguous: More than one distinct USB serial.
    """
    groups = group_ppk2s(ports)
    if not groups:
        raise NotFound
    if len(groups) > 1:
        raise Ambiguous(len(groups))
    serial_str, paths = next(iter(groups.items()))
    return serial_str, tuple(sorted(paths))


def find_group_in_by_serial(ports: list[RawPort], usb_serial: str) -> tuple[str, tuple[str, ...]]:
    """Pick ``(usb_serial, sorted VCOM paths)`` for an exact USB-serial match.

    Raises:
        NotFound: No PPK2 with that serial in ``ports``.
    """
    groups = group_ppk2s(ports)
    paths = groups.get(usb_serial)
    if paths is None:
        raise NotFound
    return usb_serial, tuple(sorted(paths))


# ─── active data-port probe ────────────────────────────────────────────

_PROBE_BAUD = 115_200
_PROBE_READ_TIMEOUT_S = 0.1
_PROBE_SETTLE_S = 0.1  # let AVERAGE_STOP take effect before draining
_PROBE_DRAIN_S = 0.3  # budget for flushing a still-streaming backlog
_PROBE_METADATA_TIMEOUT_S = 1.0  # accumulate-until-END budget
_RECOVER_REENUM_S = 1.0  # ride out the post-RESET USB CDC re-enumeration
_RECOVER_OPEN_RETRY_S = 2.0  # ride out the post-kill CDC lock-release lag
_RECOVER_METADATA_TIMEOUT_S = 2.5  # mirror _METADATA_READ_TIMEOUT_S


def probe_port(device: str, *, recover: bool = False) -> PortStatus:
    """Classify one VCOM path by active protocol probe.

    Single attempt, short budgets, no ``RESET``: open, send
    ``AVERAGE_STOP`` (a live stream would corrupt the response), let
    it settle ~0.1 s, clear + drain the input (~0.3 s budget), send
    ``GET_METADATA`` and accumulate the response until ``END``
    (~1.0 s budget), then parse it. The port is closed before
    returning, whatever the outcome.

    With ``recover=True`` the probe runs the session-style recovery
    instead — see [`probe_port_recover`][]. Escalation only: it costs
    seconds on a silent VCOM, so callers run it just when the quick
    pass found nothing.

    Returns:
        ``"data"`` when the port answered with parseable metadata,
        ``"idle"`` when it opened but never answered (the secondary
        VCOM), ``"busy"`` when it could not be opened (almost always
        held by another process).
    """
    try:
        # exclusive=True (POSIX: flock LOCK_EX | LOCK_NB) so a port
        # held by another lock-respecting process (a live capture
        # from this package, a serialport-rs binary) classifies as
        # busy instead of silently double-opening the CDC device.
        port = serial.Serial(
            device,
            baudrate=_PROBE_BAUD,
            timeout=_PROBE_READ_TIMEOUT_S,
            write_timeout=_PROBE_READ_TIMEOUT_S,
            exclusive=True,
        )
    except (serial.SerialException, OSError):
        return "busy"
    if recover:
        return probe_port_recover(device)
    try:
        port.write(bytes([Opcode.AVERAGE_STOP.byte()]))
        sleep(_PROBE_SETTLE_S)
        with suppress(serial.SerialException, OSError):
            port.reset_input_buffer()
        _drain_input(port, _PROBE_DRAIN_S)
        port.write(bytes([Opcode.GET_METADATA.byte()]))
        buf = read_until_end(port, _PROBE_METADATA_TIMEOUT_S)
        parse_metadata(buf)
    except (OSError, MetadataError):
        # SerialException and TimeoutError are both OSError subclasses:
        # opens-but-doesn't-answer-the-protocol = the secondary VCOM.
        return "idle"
    else:
        return "data"
    finally:
        with suppress(serial.SerialException, OSError):
            port.close()


def probe_port_recover(device: str) -> PortStatus:
    """The escalation tier: session-style recovery, then the metadata probe.

    For the post-session window where the firmware stops answering
    ``GET_METADATA`` until reset. ``RESET`` makes the device drop off
    USB and re-enumerate (~200-500 ms on macOS), killing whatever port
    is open — so unlike the session handshake this runs in two opens:
    stop + ``RESET``, close, ride out the re-enum, reopen fresh, then
    query metadata with the session's 2.5 s budget. The device path
    survives re-enumeration (it derives from the USB serial). Both
    opens retry for a bounded window: right after a killed session the
    CDC driver can refuse opens for a second or two before the
    opens-but-silent phase begins.

    ``RESET`` at teardown is banned for good reason (see
    ``Session.close``): fired and abandoned, the re-enum wedges the
    next opener. Here the sender absorbs it — the wait + reopen-retry
    are what make the reset safe; do not remove them. Side effect: a
    reset drops any latched DUT power, which only matters in the
    killed-``--hold`` state this probe exists to repair.
    """
    port = _open_with_retry(device, _RECOVER_OPEN_RETRY_S)
    if port is None:
        return "busy"
    try:
        with suppress(serial.SerialException, OSError):
            port.write(bytes([Opcode.AVERAGE_STOP.byte()]))
            sleep(_PROBE_SETTLE_S)
            port.write(bytes([Opcode.RESET.byte()]))
    finally:
        with suppress(serial.SerialException, OSError):
            port.close()
    sleep(_RECOVER_REENUM_S)

    port = _open_with_retry(device, _RECOVER_OPEN_RETRY_S)
    if port is None:
        return "busy"
    try:
        with suppress(serial.SerialException, OSError):
            port.reset_input_buffer()
        _drain_input(port, _PROBE_DRAIN_S)
        port.write(bytes([Opcode.GET_METADATA.byte()]))
        buf = read_until_end(port, _RECOVER_METADATA_TIMEOUT_S)
        parse_metadata(buf)
    except (OSError, MetadataError):
        return "idle"
    else:
        return "data"
    finally:
        with suppress(serial.SerialException, OSError):
            port.close()


def _open_with_retry(device: str, budget_s: float) -> serial.Serial | None:
    """Open ``device`` exclusively, retrying failures up to ``budget_s``."""
    deadline = monotonic() + budget_s
    while True:
        try:
            return serial.Serial(
                device,
                baudrate=_PROBE_BAUD,
                timeout=_PROBE_READ_TIMEOUT_S,
                write_timeout=_PROBE_READ_TIMEOUT_S,
                exclusive=True,
            )
        except (serial.SerialException, OSError):
            if monotonic() >= deadline:
                return None
            sleep(0.25)


def _drain_input(port: serial.Serial, budget_s: float) -> None:
    """Read and discard whatever is in the input buffer, up to ``budget_s``."""
    deadline = monotonic() + budget_s
    while monotonic() < deadline:
        try:
            waiting = port.in_waiting
        except (serial.SerialException, OSError):
            return
        if waiting == 0:
            return
        try:
            port.read(waiting)
        except (serial.SerialException, OSError):
            return
        sleep(0.02)


def probe_data_port(
    paths: tuple[str, ...],
    probe: ProbeFn,
    recover_probe: ProbeFn | None = None,
) -> str | None:
    """Return the first path (lex-lowest first) that answers the probe, else None.

    When the quick pass finds nothing and ``recover_probe`` is given,
    the candidates get a second, recovery-grade pass.
    """
    for path in sorted(paths):
        if probe(path) == "data":
            return path
    if recover_probe is not None:
        for path in sorted(paths):
            if recover_probe(path) == "data":
                return path
    return None


def classify_ports(
    paths: tuple[str, ...],
    probe: ProbeFn,
    recover_probe: ProbeFn | None = None,
) -> dict[str, PortStatus]:
    """Probe ``paths`` in order until a data port answers; mark the rest idle.

    Stopping at the first data hit keeps the common case to one port
    open — the remaining VCOMs of that device are idle by definition.
    When nothing answers, every path ends up probed, so the caller can
    distinguish ``busy`` (held elsewhere) from ``idle`` (silent) — and,
    if ``recover_probe`` is given, the paths get a second,
    recovery-grade pass: idle ones first (the likelier mislabelled
    data port), then busy ones (post-kill lock-release lag also reads
    as busy; a truly held port stays busy after the recovery retry).
    """
    statuses: dict[str, PortStatus] = {}
    for path in paths:
        statuses[path] = probe(path)
        if statuses[path] == "data":
            break
    for path in paths:
        statuses.setdefault(path, "idle")
    if recover_probe is not None and "data" not in statuses.values():
        by_priority = [p for p in paths if statuses[p] == "idle"] + [
            p for p in paths if statuses[p] == "busy"
        ]
        for path in by_priority:
            statuses[path] = recover_probe(path)
            if statuses[path] == "data":
                break
    return statuses


def build_listings(
    ports: list[RawPort],
    probe: ProbeFn,
    recover_probe: ProbeFn | None = None,
) -> list[Ppk2Listing]:
    """Assemble [`Ppk2Listing`][] rows from an enumeration snapshot + probe."""
    out: list[Ppk2Listing] = []
    for usb_serial, paths in sorted(group_ppk2s(ports).items()):
        ordered = tuple(sorted(paths))
        statuses = classify_ports(ordered, probe, recover_probe)
        data_port = next((p for p in ordered if statuses[p] == "data"), None)
        out.append(
            Ppk2Listing(
                usb_serial=usb_serial,
                ports=ordered,
                data_port=data_port,
                statuses=statuses,
            )
        )
    return out


def resolve_probes(probe: ProbeFn | None) -> tuple[ProbeFn, ProbeFn | None]:
    """Real probe pair when none injected; injected probe alone otherwise.

    Test doubles come in through ``probe``; escalation stays off for
    them unless the test wires ``recover_probe`` explicitly at the
    composition-primitive level.
    """
    if probe is None:
        return probe_port, probe_port_recover
    return probe, None


def _poll_until_found(
    timeout_s: float,
    try_find: "_GroupFindFn",
    probe: ProbeFn | None,
) -> PortInfo:
    """Retry enumeration + probe every 250 ms until success or timeout.

    [`Ambiguous`][] is raised immediately — polling won't help
    disambiguate a multi-PPK2 bench. Enumeration misses and probe
    misses both keep polling until the deadline: the probe runs inside
    the loop so a half-enumerated device (its VCOMs registered but the
    firmware not yet answering) resolves on a later tick.
    """
    quick, recover = resolve_probes(probe)
    deadline = monotonic() + timeout_s
    while True:
        ports = enumerate_ports()
        try:
            serial_str, paths = try_find(ports)
        except Ambiguous:
            raise
        except DiscoveryError:
            if monotonic() >= deadline:
                raise
        else:
            device = probe_data_port(paths, quick, recover)
            if device is not None:
                return PortInfo(device=device, usb_serial=serial_str)
            if monotonic() >= deadline:
                raise DataPortNotFound(paths)
        # 250 ms — long enough that we don't hammer IOKit/udev on every
        # poll, short enough that a re-enum surfaces within 1-2 ticks.
        sleep(0.25)


_GroupFindFn = Callable[[list[RawPort]], tuple[str, tuple[str, ...]]]
