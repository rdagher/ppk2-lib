"""``ppk2 list`` — enumerate connected PPK2s and tag each VCOM's probe status."""

import typer

from ppk2 import list_ppk2s
from ppk2.client.discovery import PortStatus

_STATUS_TAGS: dict[PortStatus, str] = {
    "data": "[data port]",
    "idle": "[idle]",
    "busy": "[busy — held by another process?]",
}


def list_devices() -> None:
    """Print one block per physical PPK2 with each VCOM's probe status.

    Exit code 0 when every enumerated device has an identified data
    port; 1 when none is plugged in or when a device's data port could
    not be identified (typically because another process holds it).
    """
    devices = list_ppk2s()
    if not devices:
        typer.echo("no PPK2 found")
        raise typer.Exit(code=1)
    unidentified = False
    for dev in devices:
        typer.echo(f"PPK2  serial={dev.usb_serial}")
        for path in dev.ports:
            typer.echo(f"  {path}   {_STATUS_TAGS[dev.statuses[path]]}")
        if dev.data_port is None:
            unidentified = True
            typer.echo(
                "  (data port not identified — close the nRF Connect Power "
                "Profiler if it's open, else pass --port)"
            )
    if unidentified:
        raise typer.Exit(code=1)
