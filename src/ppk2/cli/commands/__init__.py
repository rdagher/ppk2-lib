"""Per-subcommand modules for the ``ppk2`` CLI.

``resolve_device``, shared by all of them, turns the ``--serial`` /
``--port`` flag pair into a device path.
"""

from ppk2 import Mode, find_ppk2, find_ppk2_by_serial

#: The modes under the names of Nordic's app, for messages.
MODE_LABELS: dict[int, str] = {Mode.AMPERE: "Ampere meter", Mode.SOURCE: "Source meter"}


def resolve_device(serial: str | None, port: str | None) -> str:
    """Resolve the data-port path from the ``--serial``/``--port`` flags.

    ``--port`` wins and skips discovery and the probe: the caller says
    they know the path. Otherwise discovery runs, scoped to ``--serial``
    when given.
    """
    if port is not None:
        return port
    info = find_ppk2_by_serial(serial) if serial else find_ppk2()
    return info.device
