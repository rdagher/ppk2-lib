"""Top-level Typer app + dispatch.

The ``ppk2`` binary is registered as ``ppk2 = ppk2.cli.main:main`` in
``pyproject.toml``; ``python -m ppk2`` resolves through
``ppk2.__main__`` to the same entry point. [`main`][] wraps the Typer
app with the top-level error mapping: expected failure modes (no
device, wedged handshake, serial I/O) exit with a clean one-line
stderr diagnostic instead of a traceback.
"""

import sys
from pathlib import Path
from typing import Annotated

import serial
import typer

from ppk2 import DiscoveryError, SessionError
from ppk2.cli.commands import capture as _capture
from ppk2.cli.commands import discover as _discover
from ppk2.cli.commands import list_devices as _list_devices
from ppk2.cli.commands import metadata as _metadata
from ppk2.cli.commands import power as _power
from ppk2.cli.commands import run as _run

app = typer.Typer(
    name="ppk2",
    help="Command-line frontend for Nordic's Power Profiler Kit II.",
    no_args_is_help=True,
    add_completion=False,
)

_SerialOption = Annotated[
    str | None,
    typer.Option(
        "--serial",
        help="USB serial of a specific PPK2 (required when more than one is plugged in).",
    ),
]
_PortOption = Annotated[
    str | None,
    typer.Option(
        "--port",
        help=(
            "PPK2 data-port device path (e.g. /dev/cu.usbmodem…). "
            "Bypasses discovery and the data-port probe entirely."
        ),
    ),
]
_VddOption = Annotated[
    float,
    typer.Option(
        "--vdd",
        help=(
            "DUT VDD in volts. Source mode: regulator setpoint; ammeter mode: "
            "feeds the calibration math, so set it to the DUT's real rail. "
            "Clamped to [0.8, 5.0]."
        ),
    ),
]
_SourceOption = Annotated[
    bool,
    typer.Option(
        "--source",
        help="Use source mode (PPK2 supplies VDD) instead of the default ammeter mode.",
    ),
]


@app.command()
def version() -> None:
    """Print the package version and exit."""
    from ppk2 import __version__

    typer.echo(__version__)


@app.command()
def discover(serial: _SerialOption = None, port: _PortOption = None) -> None:
    """Print the discovered PPK2's data-port device path."""
    _discover.discover(serial, port)


@app.command("list")
def list_() -> None:
    """List connected PPK2s and tag each VCOM (data port / idle / busy)."""
    _list_devices.list_devices()


@app.command()
def metadata(serial: _SerialOption = None, port: _PortOption = None) -> None:
    """Print the per-device calibration coefficients."""
    _metadata.metadata(serial, port)


@app.command()
def power(
    state: Annotated[
        _power.PowerState,
        typer.Argument(case_sensitive=False, help="`on` closes the FET; `off` opens it."),
    ],
    serial: _SerialOption = None,
    port: _PortOption = None,
    hold: Annotated[
        bool,
        typer.Option("--hold", help="Hold the FET state until SIGINT (only meaningful with `on`)."),
    ] = False,
    vdd: _VddOption = 3.3,
    source: _SourceOption = False,
) -> None:
    """Toggle the DUT-power FET on or off."""
    _power.power(serial, port, state, hold, vdd, source)


@app.command()
def capture(
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output CSV path."),
    ],
    serial: _SerialOption = None,
    port: _PortOption = None,
    seconds: Annotated[
        float,
        typer.Option("--seconds", "-s", help="Capture duration in seconds."),
    ] = 30.0,
    vdd: _VddOption = 3.3,
    source: _SourceOption = False,
    user_gain: Annotated[
        list[str] | None,
        typer.Option(
            "--user-gain",
            help=(
                "Per-range user gain override, RANGE:GAIN. Repeatable; "
                "e.g. --user-gain 2:1.05 --user-gain 4:0.98. Applied "
                "host-side via Session.set_user_gain."
            ),
        ),
    ] = None,
) -> None:
    """Capture the current trace to a CSV file (GUI-parity 11-column format)."""
    _capture.capture(serial, port, out, seconds, vdd, source, user_gain or ())


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(
    ctx: typer.Context,
    serial: _SerialOption = None,
    port: _PortOption = None,
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Optional CSV output path for the child's runtime."),
    ] = None,
    vdd: _VddOption = 3.3,
    source: _SourceOption = False,
) -> None:
    """Run a shell command with the DUT powered, optionally capturing the trace."""
    cmd = list(ctx.args)
    exit_code = _run.run(serial, port, cmd, out, vdd, source)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


# ─── top-level error mapping ────────────────────────────────────────────

#: Hint appended when a serial failure carries errno 16 (EBUSY): the
#: port is held by another process — in practice, Nordic's GUI.
_ERRNO16_HINT = " — close the nRF Connect Power Profiler (or any other process holding the port)"


def errno16_in_chain(exc: BaseException) -> bool:
    """True when ``exc`` or anything in its cause/context chain is EBUSY (errno 16).

    Module-public so tests can pin the chain walk; not part of the
    documented API.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == 16:
            return True
        current = current.__cause__ or current.__context__
    return False


def dispatch(argv: list[str] | None = None) -> int:
    """Invoke the Typer app and map failures to exit codes + one-line stderr.

    The app runs in Typer's standalone mode, so CLI usage errors keep
    Typer's own rendering (usage + hint, exit 2) and a Ctrl-C inside a
    command keeps Typer's conventional exit 130 — those arrive here as
    ``SystemExit`` and are passed through. What this wrapper adds is
    the mapping for the library's expected failure modes, which must
    never show a traceback:

    - [`DiscoveryError`][ppk2.DiscoveryError] /
      [`SessionError`][ppk2.SessionError] → ``error: …`` + exit 1.
    - Serial I/O errors → ``error: serial I/O failed …`` + exit 1.
    - Either kind appends the close-the-Power-Profiler hint when
      errno 16 (``EBUSY`` — the port is held by another process) is
      anywhere in the exception's cause chain.

    A Ctrl-C *during* capture never reaches this mapping as an
    exception: the capture command handles it (CSV flushed, its own
    exit 130).

    Args:
        argv: CLI arguments without the program name. ``None`` uses
            ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    try:
        app(args=argv, prog_name="ppk2")
    except SystemExit as exc:
        # Typer's standalone exit path: success (0), usage errors (2),
        # typer.Exit codes, and Ctrl-C inside a command (130).
        return _systemexit_code(exc)
    except KeyboardInterrupt:
        # Belt and braces: an interrupt outside Typer's own guard
        # (it maps in-command Ctrl-C to exit 130 itself).
        sys.stderr.write("interrupted\n")
        return 130
    except (DiscoveryError, SessionError) as exc:
        hint = _ERRNO16_HINT if errno16_in_chain(exc) else ""
        sys.stderr.write(f"error: {exc}{hint}\n")
        return 1
    except serial.SerialException as exc:
        hint = _ERRNO16_HINT if errno16_in_chain(exc) else ""
        sys.stderr.write(f"error: serial I/O failed ({exc}){hint}\n")
        return 1
    return 0


def _systemexit_code(exc: SystemExit) -> int:
    """Normalize ``SystemExit.code`` to an int, mirroring ``sys.exit`` semantics."""
    if exc.code is None:
        return 0
    if isinstance(exc.code, int):
        return exc.code
    sys.stderr.write(f"{exc.code}\n")
    return 1


def main() -> None:
    """Console-script entry point: run [`dispatch`][] and exit with its code."""
    raise SystemExit(dispatch())
