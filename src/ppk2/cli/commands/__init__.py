"""Per-subcommand modules for the ``ppk2`` CLI.

Each submodule registers a single Typer subcommand on the root
[`ppk2.cli.main.app`][]. The split keeps each subcommand's logic
self-contained and unit-testable.

Shared across the modules: [`resolve_device`][] turns the
``--serial`` / ``--port`` flag pair into a concrete device path.
"""

from ppk2 import find_ppk2, find_ppk2_by_serial


def resolve_device(serial: str | None, port: str | None) -> str:
    """Resolve the target data-port path from the ``--serial``/``--port`` flags.

    ``--port`` wins and bypasses discovery AND the active data-port
    probe entirely — the caller asserts they know the right path.
    Otherwise discovery runs (scoped to ``--serial`` when given),
    including the probe.
    """
    if port is not None:
        return port
    info = find_ppk2_by_serial(serial) if serial else find_ppk2()
    return info.device
