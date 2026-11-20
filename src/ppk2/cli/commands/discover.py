"""``ppk2 discover``: print the data-port device path of the plugged-in PPK2."""

import typer

from ppk2.cli.commands import resolve_device


def discover(serial: str | None, port: str | None) -> None:
    """Resolve the PPK2 and print its data-port device path to stdout.

    With ``--port`` the path is echoed back as given, with no discovery
    and no probe, so scripts can pass the flag to every subcommand.
    """
    typer.echo(resolve_device(serial, port))
