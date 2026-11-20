"""``ppk2 run``: run a command with the DUT powered, optionally capturing the trace."""

import os
import signal
import subprocess
import sys
import threading
from contextlib import suppress
from pathlib import Path

import typer

from ppk2 import Mode, Sample, Session
from ppk2.cli.commands import MODE_LABELS, resolve_device
from ppk2.cli.csv import noise_floor, vdd_to_mv
from ppk2.cli.signals import signals_to_systemexit
from ppk2.cli.trace import TraceFile


def run(
    serial: str | None,
    port: str | None,
    cmd: list[str],
    out: Path | None,
    vdd: float,
    source: bool,
) -> int:
    """Spawn ``cmd`` with the DUT powered, optionally writing the trace to ``out``.

    Returns the child's exit code so the caller can forward it.
    """
    if not cmd:
        typer.echo("ppk2: run requires a command after `--`", err=True)
        return 2

    device = resolve_device(serial, port)
    mv = vdd_to_mv(vdd)
    mode = Mode.SOURCE if source else Mode.AMPERE

    sys.stderr.write(f"opening session ({MODE_LABELS[mode]} mode, vdd={mv} mV)\n")
    sys.stderr.flush()

    trace: TraceFile | None = None
    try:
        # SIGTERM/SIGHUP -> SystemExit: a kill or closed terminal unwinds
        # this stack so the session tears down and the file is completed.
        with signals_to_systemexit("SIGTERM", "SIGHUP"), Session.open(device) as session:
            if out is not None:
                # Opened once the PPK2 answers: a run that cannot start
                # leaves an earlier file of the same name alone.
                out.parent.mkdir(parents=True, exist_ok=True)
                trace = TraceFile(out)
            session.set_mode(mode)
            session.set_source_voltage(mv)
            session.start_measuring()
            # latch_s=0 + one-shot backlog drop: the reader thread's own
            # reads cover the time the switch takes, and the trace
            # starts near power-on so the child's boot inrush is captured.
            session.power_on(latch_s=0.0)
            session.drop_pending_backlog()

            stop_event = threading.Event()
            reader_thread = threading.Thread(
                target=_drain_samples,
                args=(session, trace, stop_event),
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
        if trace is not None:
            trace.close()

    sys.stderr.write(f"child exit code: {exit_code}\n")
    return exit_code


def spawn_and_wait(cmd: list[str]) -> int:
    """Run ``cmd`` in its own session, forward Ctrl-C, return its exit code.

    In its own process group the child does not get the terminal's
    Ctrl-C: this wrapper does, forwards ``SIGINT`` to the child's group,
    waits, and returns its code. Otherwise both would race for the same
    signal and the PPK2 teardown could interleave with the child's
    shutdown.

    A missing executable returns 127 and a signal-killed child
    ``128 + N``, as a shell would.
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
    trace: TraceFile | None,
    stop_event: threading.Event,
) -> None:
    """Run ``Session.capture`` until ``stop_event`` is set; write to ``trace`` if given.

    The stream is drained even when nothing is written: the firmware
    cannot pause it. A serial failure is reported on stderr, never
    swallowed: a dead reader truncates the trace and leaves the stream
    undrained, and the operator needs to know.
    """

    def emit(s: Sample) -> bool:
        if stop_event.is_set():
            return False
        if trace is not None:
            # Real values pass through the app's 0.2 µA clamp first.
            trace.add(noise_floor(s.current_micro_amps), s.logic)
        return True

    try:
        session.capture(emit)
    except Exception as exc:
        sys.stderr.write(
            f"ppk2: capture reader stopped ({exc}): the trace is incomplete "
            "and the stream is no longer being drained\n"
        )
        sys.stderr.flush()
