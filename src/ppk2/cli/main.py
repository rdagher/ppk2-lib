"""The ``ppk2`` Typer app and its error mapping.

``main`` is the entry point of the ``ppk2`` binary and of
``python -m ppk2``. It wraps the app so that the expected failures (no
device, wedged handshake, serial I/O) exit with a one-line message
instead of a traceback.
"""

import sys
from pathlib import Path
from typing import Annotated

import serial
import typer

from ppk2 import DiscoveryError, SessionError
from ppk2.cli.commands import capture as _capture
from ppk2.cli.commands import convert as _convert
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
            "DUT supply voltage in volts. Source meter mode: what the PPK2 "
            "outputs. Ampere meter mode: only feeds the calibration, so give "
            "the DUT's real supply voltage. Clamped to [0.8, 5.0]."
        ),
    ),
]
_SourceOption = Annotated[
    bool,
    typer.Option(
        "--source",
        help=(
            "Use Source meter mode (the PPK2 supplies the DUT) instead of "
            "the default, Ampere meter mode."
        ),
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
    """List connected PPK2s and mark each serial port: data port, idle or busy."""
    _list_devices.list_devices()


@app.command()
def metadata(serial: _SerialOption = None, port: _PortOption = None) -> None:
    """Print the per-device calibration coefficients."""
    _metadata.metadata(serial, port)


@app.command()
def power(
    state: Annotated[
        _power.PowerState,
        typer.Argument(case_sensitive=False, help="`on` powers the DUT; `off` cuts its power."),
    ],
    serial: _SerialOption = None,
    port: _PortOption = None,
    hold: Annotated[
        bool,
        typer.Option("--hold", help="Keep the power on until Ctrl-C (only meaningful with `on`)."),
    ] = False,
    vdd: _VddOption = 3.3,
    source: _SourceOption = False,
) -> None:
    """Switch power to the DUT on or off, like the app's Enable power output.

    Power lasts only while the command runs: use --hold to keep it on.
    """
    _power.power(serial, port, state, hold, vdd, source)


@app.command()
def capture(
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            "-o",
            help="Output path: a CSV, or a Power Profiler session file if it ends in .ppk2.",
        ),
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
                "Per-range user gain override, RANGE:GAIN, with RANGE from 0 to 4 "
                "(the app numbers the ranges 1 to 5). Repeatable; "
                "e.g. --user-gain 2:1.05 --user-gain 4:0.98. Applied "
                "host-side via Session.set_user_gain."
            ),
        ),
    ] = None,
) -> None:
    """Capture the trace to a CSV file (the app's export format) or to a .ppk2 file."""
    _capture.capture(serial, port, out, seconds, vdd, source, user_gain or ())


@app.command()
def convert(
    src: Annotated[Path, typer.Argument(help="CSV capture, plain or .gz.")],
    dst: Annotated[Path, typer.Argument(help="Output .ppk2 path.")],
) -> None:
    """Convert a CSV capture to a .ppk2 file for Nordic's Power Profiler app."""
    _convert.convert(src, dst)


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(
    ctx: typer.Context,
    serial: _SerialOption = None,
    port: _PortOption = None,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            "-o",
            help="Optional trace output: a CSV, or a session file if the name ends in .ppk2.",
        ),
    ] = None,
    vdd: _VddOption = 3.3,
    source: _SourceOption = False,
) -> None:
    """Run a command with the DUT powered, optionally capturing the trace.

    The command goes after `--`: ppk2 run --source --vdd 3.0 -- west flash
    """
    cmd = list(ctx.args)
    exit_code = _run.run(serial, port, cmd, out, vdd, source)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


# ─── top-level error mapping ────────────────────────────────────────────

#: Hint appended when a serial failure carries errno 16 (EBUSY): the
#: port is held by another process, in practice Nordic's app.
_ERRNO16_HINT = " (close the nRF Connect Power Profiler, or whatever else holds the port)"


def errno16_in_chain(exc: BaseException) -> bool:
    """Whether ``exc`` or anything in its cause/context chain is EBUSY (errno 16)."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno == 16:
            return True
        current = current.__cause__ or current.__context__
    return False


def dispatch(argv: list[str] | None = None) -> int:
    """Run the app and map failures to an exit code and one line on stderr.

    Typer keeps its own handling of usage errors (exit 2) and of Ctrl-C
    inside a command (exit 130): those arrive here as ``SystemExit`` and
    pass through. Added here, so that the library's expected failures
    never show a traceback:

    - ``DiscoveryError`` / ``SessionError`` -> ``error: …``, exit 1.
    - Serial I/O errors -> ``error: serial I/O failed …``, exit 1.
    - Either gets a close-the-Power-Profiler hint when errno 16 (the port
      is held by another process) is in the cause chain.

    A Ctrl-C during a capture does not come through here: the capture
    command handles it itself (CSV flushed, exit 130).

    Args:
        argv: Arguments without the program name; ``sys.argv[1:]`` when
            ``None``.

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
    """Console-script entry point: run ``dispatch`` and exit with its code."""
    raise SystemExit(dispatch())
