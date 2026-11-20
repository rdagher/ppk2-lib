"""Route termination signals to ``SystemExit`` so the session teardown runs.

``kill <pid>`` (SIGTERM) or a closed terminal (SIGHUP) would otherwise
end the process without unwinding the ``with`` stack: no
``AVERAGE_STOP`` is sent and the PPK2 keeps streaming into a dead
session, which wedges the next open. Raising ``SystemExit`` from the
handler unwinds the context managers instead, same as a Ctrl-C stop.
"""

import signal
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from types import FrameType

# Matches `signal.signal`'s handler union: the SIG_DFL / SIG_IGN
# sentinels or a Python callable.
_SignalHandler = Callable[[int, FrameType | None], object] | int | None


@contextmanager
def signals_to_systemexit(*names: str) -> Generator[None, None, None]:
    """Route the named signals (e.g. ``"SIGTERM"``) to ``SystemExit`` for the block.

    The exit code is the conventional ``128 + signum``; the previous
    handlers come back on exit. A signal that cannot be installed is
    skipped: a name this OS lacks (no ``SIGHUP`` on Windows), or a call
    off the main thread, where ``signal.signal`` raises ``ValueError``.
    """

    def _raise(signum: int, _frame: FrameType | None) -> None:
        raise SystemExit(128 + signum)

    previous: dict[int, _SignalHandler] = {}
    for name in names:
        sig = getattr(signal, name, None)
        if sig is None:
            continue  # not on this OS
        # signal.signal raises ValueError off the main thread.
        with suppress(ValueError):
            previous[sig] = signal.signal(sig, _raise)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            with suppress(ValueError, OSError):
                signal.signal(sig, handler)
