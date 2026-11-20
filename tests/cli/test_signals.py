"""signals_to_systemexit tests: real signals delivered in-process, no hardware."""

import signal
import threading

import pytest

from ppk2.cli.signals import signals_to_systemexit


def test_sigterm_raises_systemexit_with_conventional_code() -> None:
    """SIGTERM inside the block unwinds via SystemExit(128 + signum)."""
    with pytest.raises(SystemExit) as exc, signals_to_systemexit("SIGTERM"):
        signal.raise_signal(signal.SIGTERM)
    assert exc.value.code == 128 + signal.SIGTERM


def test_previous_handler_restored_on_exit() -> None:
    def previous(_signum: int, _frame: object) -> None:  # pragma: no cover - never fired
        raise AssertionError("should not fire")

    original = signal.signal(signal.SIGTERM, previous)
    try:
        with signals_to_systemexit("SIGTERM"):
            assert signal.getsignal(signal.SIGTERM) is not previous
        assert signal.getsignal(signal.SIGTERM) is previous
    finally:
        signal.signal(signal.SIGTERM, original)


def test_previous_handler_restored_when_the_signal_fires() -> None:
    """The finally-restore also runs on the SystemExit unwind path."""
    original = signal.getsignal(signal.SIGTERM)
    with pytest.raises(SystemExit), signals_to_systemexit("SIGTERM"):
        signal.raise_signal(signal.SIGTERM)
    assert signal.getsignal(signal.SIGTERM) is original


def test_absent_signal_names_are_skipped() -> None:
    """A name this OS doesn't define (e.g. SIGHUP on Windows) is skipped, not fatal."""
    with signals_to_systemexit("SIGDOESNOTEXIST"):
        pass


def test_off_main_thread_installation_is_tolerated() -> None:
    """signal.signal raises ValueError off the main thread: the CM must still yield."""
    outcome: list[str] = []

    def body() -> None:
        with signals_to_systemexit("SIGTERM"):
            outcome.append("entered")

    worker = threading.Thread(target=body, name="signals-offthread")
    worker.start()
    worker.join(timeout=5.0)
    assert outcome == ["entered"]
