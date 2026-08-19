"""Route termination signals to ``SystemExit`` so session teardown runs.

``kill <pid>`` (SIGTERM) or a closed terminal (SIGHUP) would otherwise
end the process without unwinding the ``with`` stack — leaving the FET
closed, the port open, and the firmware streaming into a dead CDC
session (which wedges the next open). Raising ``SystemExit`` from the
handler unwinds the enclosing context managers instead: the session
closes (stream stopped, FET opened, port closed) and any CSV file is
flushed, same as a Ctrl-C stop.
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
    """Temporarily route the named signals (e.g. ``"SIGTERM"``) to ``SystemExit``.

    The exit code is the conventional ``128 + signum``. Previous
    handlers are restored on exit. Signals that can't be installed are
    skipped silently: a name absent on this OS (Windows has no
    ``SIGHUP``) or installation off the main thread (``signal.signal``
    raises ``ValueError`` there — e.g. when a capture helper runs in a
    worker thread).

    Args:
        names: ``signal`` module attribute names, e.g. ``"SIGTERM"``,
            ``"SIGHUP"``.
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
