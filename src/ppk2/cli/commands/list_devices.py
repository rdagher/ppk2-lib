"""``ppk2 list``: enumerate connected PPK2s and mark each port's probe status."""

import typer

from ppk2 import list_ppk2s
from ppk2.client.discovery import PortStatus

_STATUS_TAGS: dict[PortStatus, str] = {
    "data": "[data port]",
    "idle": "[idle]",
    "busy": "[busy: held by another process?]",
}


def list_devices(mask_serial: bool = False) -> None:
    """Print one block per physical PPK2 with each port's probe status.

    Exit code 0 when every enumerated device has an identified data
    port; 1 when none is plugged in or when a device's data port could
    not be identified (typically because another process holds it).

    With ``mask_serial`` only the last four characters of each serial
    number are printed, in the port paths too: for a screenshot or a
    recording.
    """
    devices = list_ppk2s()
    if not devices:
        typer.echo("no PPK2 found")
        raise typer.Exit(code=1)
    unidentified = False
    for dev in devices:
        serial = dev.usb_serial
        masked = "*" * (len(serial) - 4) + serial[-4:] if mask_serial else serial
        typer.echo(f"PPK2  serial={masked}")
        for path in dev.ports:
            shown = path.replace(serial, masked) if serial else path
            typer.echo(f"  {shown}   {_STATUS_TAGS[dev.statuses[path]]}")
        if dev.data_port is None:
            unidentified = True
            typer.echo(
                "  (data port not identified: close the nRF Connect Power "
                "Profiler if it's open, else pass --port)"
            )
    if unidentified:
        raise typer.Exit(code=1)
