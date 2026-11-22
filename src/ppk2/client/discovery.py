"""PPK2 port discovery.

A PPK2 shows up as two USB serial ports with identical
descriptors; only one, the data port, speaks the protocol. Discovery:

1. List the serial ports and keep those with the PPK2's USB VID/PID
   (Nordic ``0x1915`` / ``0xC00A``).
2. Group them by USB serial number. More than one device means the
   caller must pick one with ``find_ppk2_by_serial``.
3. Find the data port by probing, lowest path first (the usual hit):
   open, stop any stream, request the metadata, wait for ``END``. The
   data port answers; the other port opens but stays silent; a port
   held by another process (typically Nordic's Power Profiler app)
   does not open at all.
4. If nothing answered, probe once more with a reset: the last resort
   for a PPK2 the plain probe cannot reach.

The probe runs inside the polling loop, so a device that has only half
enumerated is probed again on the next tick.
"""

from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Literal

import serial
import serial.tools.list_ports

from ppk2.client.session import flush_input, read_until_end
from ppk2.protocol import MetadataError, Opcode, parse_metadata

#: Default polling budget for ``find_ppk2``, in seconds: long enough for
#: a PPK2 to come back on USB after a ``RESET``.
DEFAULT_DISCOVERY_TIMEOUT_S = 3.0

#: What a probe found on one port: the data port answers the metadata
#: request, the other port is idle, a port held elsewhere is busy.
PortStatus = Literal["data", "idle", "busy"]

#: A port-probe function: ``probe_port`` or a test double.
ProbeFn = Callable[[str], PortStatus]


@dataclass(frozen=True)
class PortInfo:
    """A PPK2 and the port to talk to it on.

    Attributes:
        device: Device path or COM name
            (``/dev/cu.usbmodemA1B2C3D4E5F62`` on macOS, ``COM7`` on
            Windows).
        usb_serial: USB serial number, the stable handle when several
            PPK2s are plugged in.
    """

    device: str
    usb_serial: str


@dataclass(frozen=True)
class Ppk2Listing:
    """One connected PPK2 and the status of each of its ports.

    Attributes:
        usb_serial: USB serial number of the device.
        ports: Its port paths, sorted.
        data_port: The path that answered the probe, or ``None`` when none
            did (usually another process holds the data port).
        statuses: Probe result per path. Paths left unprobed because an
            earlier one already answered are reported ``"idle"``.
    """

    usb_serial: str
    ports: tuple[str, ...]
    data_port: str | None
    statuses: dict[str, PortStatus]


class DiscoveryError(Exception):
    """Base class for port discovery failures."""


class NotFound(DiscoveryError):
    """No PPK2 (USB ``0x1915:0xC00A``) on the bus, or none with the serial asked for."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "no PPK2 found (USB 1915:C00A): plug one in or check the cable")


class Ambiguous(DiscoveryError):
    """More than one PPK2 on the bus; ``count`` is how many.

    Pick one with ``find_ppk2_by_serial``.
    """

    def __init__(self, count: int) -> None:
        super().__init__(
            f"{count} physical PPK2 devices found; pass --serial <usb-serial> to pick one"
        )
        self.count = count


class DataPortNotFound(DiscoveryError):
    """A PPK2 enumerated but no port answered the probe; ``paths`` lists them.

    Usually another process holds the data port: Nordic's Power Profiler
    app keeps it open while it runs.
    """

    def __init__(self, paths: tuple[str, ...]) -> None:
        super().__init__(
            f"could not identify the PPK2 data port: none of {list(paths)} answered "
            "GET_METADATA; close the nRF Connect Power Profiler if it is open, "
            "or pass --port to select the port explicitly"
        )
        self.paths = paths


def find_ppk2(
    *,
    timeout_s: float = DEFAULT_DISCOVERY_TIMEOUT_S,
    probe: ProbeFn | None = None,
) -> PortInfo:
    """Find the single PPK2 on the bus and return its data port.

    Polls for up to ``timeout_s`` seconds, so that a PPK2
    just plugged in, or coming back on USB, is found.

    Args:
        timeout_s: Polling budget in seconds; 0 for a single pass.
        probe: Probe function to use instead of the real one (tests).

    Raises:
        NotFound: No PPK2 on the bus.
        Ambiguous: More than one PPK2; raised at once, polling cannot
            settle it.
        DataPortNotFound: A PPK2 is there but no port answered in time.
    """
    return _poll_until_found(timeout_s, find_group_in, probe)


def find_ppk2_by_serial(
    usb_serial: str,
    *,
    timeout_s: float = DEFAULT_DISCOVERY_TIMEOUT_S,
    probe: ProbeFn | None = None,
) -> PortInfo:
    """Like ``find_ppk2``, for the PPK2 whose USB serial is exactly ``usb_serial``."""
    return _poll_until_found(
        timeout_s,
        lambda ports: find_group_in_by_serial(ports, usb_serial),
        probe,
    )


def list_ppk2s(*, probe: ProbeFn | None = None) -> list[Ppk2Listing]:
    """List connected PPK2s with the status of each port (``ppk2 list``).

    Each device's ports are probed lowest path first, stopping at the data
    port: the rest are then idle and left unprobed. When nothing answers,
    every port is probed, which tells ``busy`` (held by another process)
    from ``idle`` (silent).

    Args:
        probe: Probe function to use instead of the real one (tests).
    """
    quick, recover = resolve_probes(probe)
    return build_listings(enumerate_ports(), quick, recover)


# ─── building blocks ───────────────────────────────────────────────────
#
# The pieces the functions above are made of. Importable, but not part
# of the public API.


#: Nordic Semiconductor's USB vendor ID.
PPK2_VID: int = 0x1915

#: PPK2's USB product ID.
PPK2_PID: int = 0xC00A


@dataclass(frozen=True)
class RawPort:
    """The fields of a pyserial port entry that discovery uses."""

    device: str
    vid: int | None
    pid: int | None
    serial_number: str | None


def enumerate_ports() -> list[RawPort]:
    """Snapshot the serial ports as ``RawPort`` rows."""
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
    """Whether the port has the PPK2's USB VID/PID.

    The same selector as Nordic's app, and more reliable than product
    strings (empty on Windows, varying across firmware on Linux). Both
    ports of a PPK2 match: telling them apart is the probe's job.
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


def find_group_in(ports: list[RawPort]) -> tuple[str, tuple[str, ...]]:
    """Pick the single PPK2's ``(usb_serial, sorted port paths)`` from ``ports``.

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
    """Pick ``(usb_serial, sorted port paths)`` for an exact USB-serial match.

    Raises:
        NotFound: No PPK2 with that serial in ``ports``.
    """
    groups = group_ppk2s(ports)
    paths = groups.get(usb_serial)
    if paths is None:
        if not groups:
            raise NotFound
        raise NotFound(f"no PPK2 with serial {usb_serial}: attached {', '.join(sorted(groups))}")
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


def probe_port(device: str) -> PortStatus:
    """Classify one port by probing it once, without ``RESET``.

    Open, send ``AVERAGE_STOP`` (a live stream would garble the answer),
    let it settle, drain the input, request the metadata and wait up to
    ~1 s for a parseable response. The port is closed before returning.

    Returns:
        ``"data"`` if it answered with metadata, ``"idle"`` if it opened
        but stayed silent (the other port), ``"busy"`` if it would not
        open (almost always held by another process).
    """
    try:
        # exclusive=True (POSIX flock): a port held by a lock-respecting
        # process, such as a live capture from this package, classifies
        # as busy instead of being opened a second time.
        port = serial.Serial(
            device,
            baudrate=_PROBE_BAUD,
            timeout=_PROBE_READ_TIMEOUT_S,
            write_timeout=_PROBE_READ_TIMEOUT_S,
            exclusive=True,
        )
    except (serial.SerialException, OSError):
        return "busy"
    try:
        port.write(bytes([Opcode.AVERAGE_STOP.byte()]))
        sleep(_PROBE_SETTLE_S)
        flush_input(port)
        _drain_input(port, _PROBE_DRAIN_S)
        port.write(bytes([Opcode.GET_METADATA.byte()]))
        buf = read_until_end(port, _PROBE_METADATA_TIMEOUT_S)
        parse_metadata(buf)
    except (OSError, MetadataError):
        # SerialException and TimeoutError are both OSError: a port that
        # opens but does not answer is the other port.
        return "idle"
    else:
        return "data"
    finally:
        with suppress(serial.SerialException, OSError):
            port.close()


def probe_port_recover(device: str) -> PortStatus:
    """Probe one port with a reset first: the last resort after a plain probe.

    ``RESET`` makes the device drop off USB and re-enumerate (~200-500 ms
    on macOS), which kills the open port, so this takes two opens: stop +
    ``RESET``, close, wait, reopen, then request the metadata with the
    session's 2.5 s budget. The device path survives the re-enumeration
    (it derives from the USB serial). Both opens retry for a while: right
    after a killed session the CDC driver can refuse opens for a second
    or two.

    A ``RESET`` fired and abandoned wedges the next opener, which is why
    ``Session.close`` never sends one. Here the sender waits it out: do
    not remove the wait or the reopen retry.
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
        flush_input(port)
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
    """Return the first path, lowest first, that answers the probe, else ``None``.

    If the quick pass finds nothing and ``recover_probe`` is given, the
    paths get a second pass with it.
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
    """Probe ``paths`` in order until one is the data port; mark the rest idle.

    Stopping at the data port keeps the usual case to one port opened.
    When nothing answers, every path has been probed, which tells ``busy``
    from ``idle``; with ``recover_probe``, the paths then get a second
    pass, idle ones first (the likelier data port), then busy ones (a port
    just released by a killed process also reads as busy; one truly held
    stays busy).
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
    """Build ``Ppk2Listing`` rows from a port snapshot and a probe."""
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
    """The real probe pair by default; an injected probe alone, without escalation."""
    if probe is None:
        return probe_port, probe_port_recover
    return probe, None


def _poll_until_found(
    timeout_s: float,
    try_find: "_GroupFindFn",
    probe: ProbeFn | None,
) -> PortInfo:
    """Enumerate and probe every 250 ms until a data port is found or time runs out.

    ``Ambiguous`` is raised at once: polling cannot settle it. A device
    not found yet, or found but not answering yet, is tried again.
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
        # 250 ms: easy on IOKit/udev, and a re-enumeration shows up
        # within a tick or two.
        sleep(0.25)


_GroupFindFn = Callable[[list[RawPort]], tuple[str, tuple[str, ...]]]
