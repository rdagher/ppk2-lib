"""``ppk2 run`` — bookend a shell command with PPK2 power + optional CSV capture."""

import os
import signal
import subprocess
import sys
import threading
from contextlib import suppress
from math import isnan
from pathlib import Path
from typing import TextIO

import typer

from ppk2 import Mode, Sample, Session
from ppk2.cli.commands import resolve_device
from ppk2.cli.csv import CSV_HEADER, gui_noise_floor, vdd_to_mv, write_csv_row
from ppk2.cli.signals import signals_to_systemexit

_SAMPLE_PERIOD_MS = 0.01


def run(
    serial: str | None,
    port: str | None,
    cmd: list[str],
    out: Path | None,
    vdd: float,
    source: bool,
) -> int:
    """Spawn ``cmd`` with the FET closed, optionally streaming a CSV.

    Returns the child's exit code so the caller can forward it.
    """
    if not cmd:
        typer.echo("ppk2: run requires a command after `--`", err=True)
        return 2

    device = resolve_device(serial, port)
    mv = vdd_to_mv(vdd)
    mode = Mode.SOURCE if source else Mode.AMPERE

    sys.stderr.write(f"opening session (mode={mode.name}, vdd={mv} mV)\n")
    sys.stderr.flush()

    csv_out = None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        csv_out = out.open("w", encoding="utf-8")
        csv_out.write(f"{CSV_HEADER}\n")

    try:
        # SIGTERM/SIGHUP → SystemExit: a kill or closed terminal unwinds
        # this stack so the session tears down and the CSV flushes.
        with signals_to_systemexit("SIGTERM", "SIGHUP"), Session.open(device) as session:
            session.set_mode(mode)
            session.set_source_voltage(mv)
            session.start_measuring()
            # latch_s=0 + one-shot backlog drop: the reader thread's own
            # reads finish the FET latch, and the trace starts ≈ FET-on
            # so the child's boot inrush is captured.
            session.power_on(latch_s=0.0)
            session.drop_pending_backlog()

            stop_event = threading.Event()
            reader_thread = threading.Thread(
                target=_drain_samples,
                args=(session, csv_out, stop_event),
                name="ppk2-capture",
                daemon=True,
            )
            reader_thread.start()

            try:
                exit_code = spawn_and_wait(cmd)
            finally:
                stop_event.set()
                reader_thread.join(timeout=5.0)

            with suppress(Exception):
                session.power_off()
            with suppress(Exception):
                session.stop_measuring()
    finally:
        if csv_out is not None:
            csv_out.close()

    sys.stderr.write(f"child exit code: {exit_code}\n")
    return exit_code


def spawn_and_wait(cmd: list[str]) -> int:
    """Spawn ``cmd`` in its own session; forward Ctrl-C; return its exit code.

    ``start_new_session=True`` puts the child in its own process group
    and session, so a terminal Ctrl-C (delivered to the foreground
    group) reaches only this wrapper — which forwards ``SIGINT`` to
    the child's group, waits for it to finish, and propagates its exit
    code. Without the isolation the child would race us for the same
    SIGINT and the PPK2 teardown could interleave with the child's own
    shutdown.

    A missing executable returns 127 (the shell convention) with a
    one-line diagnostic on stderr. A signal-killed child returns
    ``128 + N`` (the shell convention) —
    ``proc.wait()``'s raw ``-N`` would otherwise reach the shell as
    ``256 - N``.
    """
    try:
        proc = subprocess.Popen(cmd, start_new_session=True)
    except FileNotFoundError:
        sys.stderr.write(f"error: command not found: {cmd[0]}\n")
        sys.stderr.flush()
        return 127
    try:
        return _shell_exit_code(proc.wait())
    except KeyboardInterrupt:
        with suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
        return _shell_exit_code(proc.wait())


def _shell_exit_code(returncode: int) -> int:
    """Map ``Popen.wait()``'s ``-N`` (killed by signal N) to shell-style ``128 + N``."""
    return 128 - returncode if returncode < 0 else returncode


def _drain_samples(
    session: Session,
    csv_out: TextIO | None,
    stop_event: threading.Event,
) -> None:
    """Run ``Session.capture`` until the parent flips ``stop_event``.

    Writes to ``csv_out`` only when one was opened; otherwise discards.
    The firmware can't be stopped mid-session without the stream going
    dark, so we always drain even when not writing.

    A serial failure in here is REPORTED to stderr, never swallowed:
    a silently dead reader stops draining the stream (the firmware
    keeps pushing into a buffer nobody empties), truncates the CSV
    without a trace, and leaves the next session to recover a wedged
    stream — the operator needs to know the trace is incomplete.
    """
    n_samples = 0
    t_ms = 0.0

    def emit(s: Sample) -> bool:
        nonlocal n_samples, t_ms
        if stop_event.is_set():
            return False
        # Data-loss placeholders advance the timeline but don't land in
        # the CSV (matches the Nordic GUI's export). Real values pass
        # through the GUI's 0.2 µA noise-floor clamp first.
        ua = gui_noise_floor(s.current_micro_amps)
        if csv_out is not None and not isnan(ua):
            write_csv_row(csv_out, t_ms, ua, s.logic)
        n_samples += 1
        t_ms += _SAMPLE_PERIOD_MS
        return True

    try:
        session.capture(emit)
    except Exception as exc:
        sys.stderr.write(
            f"ppk2: capture reader stopped ({exc}) — the trace is incomplete "
            "and the stream is no longer being drained\n"
        )
        sys.stderr.flush()
