"""``ppk2 metadata`` — print the per-device calibration coefficients."""

import typer

from ppk2 import CalibrationCoefficients, Session
from ppk2.cli.commands import resolve_device
from ppk2.cli.signals import signals_to_systemexit


def metadata(serial: str | None, port: str | None) -> None:
    """Open a session, read metadata, format-print to stdout, then teardown."""
    device = resolve_device(serial, port)
    with signals_to_systemexit("SIGTERM", "SIGHUP"), Session.open(device) as session:
        coeffs = session.coefficients()
    _print_coefficients(coeffs)


def _print_coefficients(c: CalibrationCoefficients) -> None:
    """Render the coefficient block as a human-readable table."""
    mode_name = {1: "ammeter", 2: "source"}.get(c.mode, f"unknown ({c.mode})")
    typer.echo(f"Calibrated: {'true' if c.calibrated else 'false'}")
    typer.echo(f"HW:         {c.hw}")
    typer.echo(f"IA:         {c.ia}")
    typer.echo(f"VDD:        {c.vdd_mv} mV")
    typer.echo(f"mode:       {c.mode} ({mode_name})")
    for name, arr in (
        ("R ", c.r),
        ("GS", c.gs),
        ("GI", c.gi),
        ("O ", c.o),
        ("S ", c.s),
        ("I ", c.i),
        ("UG", c.ug),
    ):
        formatted = ", ".join(f"{v: 16.6e}" for v in arr)
        typer.echo(f"{name}: [{formatted}]")
