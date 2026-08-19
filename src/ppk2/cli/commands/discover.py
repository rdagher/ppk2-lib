"""``ppk2 discover`` — print the data-port device path of the plugged-in PPK2."""

import typer

from ppk2.cli.commands import resolve_device


def discover(serial: str | None, port: str | None) -> None:
    """Resolve the PPK2 and print its data-port device path to stdout.

    With ``--port`` the path is echoed back verbatim — no discovery,
    no probe — so scripts can treat the flag uniformly across
    subcommands.
    """
    typer.echo(resolve_device(serial, port))
