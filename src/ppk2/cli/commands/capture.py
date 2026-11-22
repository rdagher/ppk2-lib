"""``ppk2 capture``: stream the current trace to a CSV or ``.ppk2`` file."""

import signal
import sys
from collections.abc import Callable, Iterable
from contextlib import ExitStack, suppress
from math import isfinite, isnan
from pathlib import Path
from time import monotonic
from types import FrameType

import typer

from ppk2 import USER_GAIN_MAX, USER_GAIN_MIN, Mode, Sample, Session
from ppk2.cli.commands import MODE_LABELS, resolve_device
from ppk2.cli.csv import noise_floor, vdd_to_mv
from ppk2.cli.signals import signals_to_systemexit
from ppk2.cli.trace import SAMPLE_RATE_HZ as _SAMPLE_RATE_HZ
from ppk2.cli.trace import TraceFile

_PROGRESS_INTERVAL_S = 1.0

#: Cumulative data-loss count at which we first emit a mid-stream
#: warning. Matches ``DATALOSS_THRESHOLD`` in Nordic's app.
_DATALOSS_WARN_THRESHOLD = 500

#: Post-capture watchdog: a realized stream rate below this fraction of
#: 100 kSPS (on captures longer than 0.5 s) means the host lost
#: samples, and charge or timing figures taken from the file are off.
_RATE_WATCHDOG_FRACTION = 0.95

#: How long past ``--seconds`` a capture waits for samples that are late.
_LATE_GRACE_S = 1.0


def capture(
    serial: str | None,
    port: str | None,
    out: Path,
    seconds: float,
    vdd: float,
    source: bool,
    user_gain_specs: Iterable[str] = (),
) -> None:
    """Open a session, stream samples for ``seconds``, write them to ``out``.

    The 11-column CSV, or a ``.ppk2`` session file when ``out`` ends in ``.ppk2``.
    """
    # Parse the gains first: a malformed flag should fail before the
    # (slow) hardware discovery, not after.
    user_gains = [parse_user_gain_spec(spec) for spec in user_gain_specs]
    if not (isfinite(seconds) and round(seconds * _SAMPLE_RATE_HZ) >= 1):
        raise typer.BadParameter(
            f"{seconds} is not a duration: give at least one sample, 0.00001 s",
            param_hint="--seconds",
        )
    mv = vdd_to_mv(vdd)
    device = resolve_device(serial, port)
    mode = Mode.SOURCE if source else Mode.AMPERE

    sys.stderr.write(f"opening session ({MODE_LABELS[mode]} mode, vdd={mv} mV)\n")
    if user_gains:
        gains_repr = ", ".join(f"r{r}={g:.4f}" for r, g in user_gains)
        sys.stderr.write(f"  user-gain overrides: {gains_repr}\n")
    sys.stderr.write(f"capturing {seconds:.2f} s -> {out} (Ctrl-C to stop early)\n")
    sys.stderr.flush()

    out.parent.mkdir(parents=True, exist_ok=True)

    stop_requested = _SigintFlag()

    # SIGTERM/SIGHUP raise SystemExit inside this block, so a `kill` or
    # a closed terminal unwinds it like a Ctrl-C: the session tears
    # down and the output file is completed.
    with ExitStack() as stack:
        stack.enter_context(stop_requested)
        stack.enter_context(signals_to_systemexit("SIGTERM", "SIGHUP"))

        with Session.open(device) as session:
            # Opened once the PPK2 answers: a capture that cannot start
            # leaves an earlier file of the same name alone.
            trace = stack.enter_context(TraceFile(out))
            session.set_mode(mode)
            session.set_source_voltage(mv)
            for range_idx, gain in user_gains:
                session.set_user_gain(range_idx, gain)
            session.start_measuring()
            session.power_on()

            n_samples = 0
            n_dataloss = 0  # NaN placeholders from the stream parser's data-loss path
            sum_ua = 0.0
            last_progress = monotonic()
            started = monotonic()
            # The capture ends on a number of samples, so that the
            # trace holds the seconds asked for. The clock ends it only
            # when the samples do not come.
            target = round(seconds * _SAMPLE_RATE_HZ)
            deadline = started + seconds + _LATE_GRACE_S
            dataloss_warned = False

            def on_dataloss(total: int) -> None:
                nonlocal dataloss_warned
                if dataloss_warned or total < _DATALOSS_WARN_THRESHOLD:
                    return
                dataloss_warned = True
                sys.stderr.write(
                    f"  warning: {total} samples lost so far, near sample "
                    f"{n_samples + n_dataloss}. Likely cause: the USB cable, a hub or a "
                    "busy computer. The capture goes on; each lost sample is recorded "
                    "as 0.2 µA, as in Nordic's app.\n"
                )
                sys.stderr.flush()

            def emit(s: Sample) -> bool:
                nonlocal n_samples, n_dataloss, sum_ua, last_progress
                if stop_requested.flag:
                    return False
                # NaN is a lost sample: 0.2 µA in the file, as in
                # Nordic's app, and left out of the mean printed here.
                ua = noise_floor(s.current_micro_amps)
                trace.add(ua, s.logic)
                if isnan(ua):
                    n_dataloss += 1
                else:
                    n_samples += 1
                    sum_ua += ua

                now = monotonic()
                if now - last_progress >= _PROGRESS_INTERVAL_S:
                    mean = sum_ua / n_samples if n_samples else 0.0
                    elapsed = now - started
                    sys.stderr.write(
                        f"  [{elapsed:5.1f}s]  {n_samples:>10} samples  mean {mean:>7.2f} µA\n"
                    )
                    sys.stderr.flush()
                    last_progress = now

                return n_samples + n_dataloss < target and monotonic() < deadline

            # The trace starts about 10 ms before power-on (Known
            # caveats in docs/measure/protocol.md).
            session.drop_pending_backlog()
            session.capture(
                emit,
                on_dataloss=on_dataloss,
                # A silent PPK2 never reaches emit: the clock and
                # Ctrl-C are checked here too.
                keep_going=lambda: not stop_requested.flag and monotonic() < deadline,
            )
            # Taken here: shutting the session down takes a tenth of a
            # second that is not capture time.
            wall = monotonic() - started

            with suppress(Exception):
                session.power_off()
            with suppress(Exception):
                session.stop_measuring()

        # Complete the file before saying so, with the signal handlers
        # still in place: a second Ctrl-C must not cut the write short.
        trace.close()
        # The stream rate counts lost samples too: they took their time.
        n_total = n_samples + n_dataloss
        rate = n_total / wall if wall > 0 else 0.0
        if stop_requested.flag:
            done = ".ppk2 written" if trace.is_ppk2 else "CSV flushed"
            sys.stderr.write(f"interrupted: {done}\n")
        suffix = ", stopped by Ctrl-C" if stop_requested.flag else ""
        sys.stderr.write(
            f"captured {n_samples} samples over {wall:.2f} s ({rate:.0f} Hz){suffix}\n"
        )
        if n_dataloss > 0:
            sys.stderr.write(
                f"  warning: {n_dataloss} samples lost "
                f"({100.0 * n_dataloss / n_total:.3f} % of the stream), "
                "each recorded as 0.2 µA, as in Nordic's app\n"
            )
        if wall > 0.5 and n_total > 0 and rate < _RATE_WATCHDOG_FRACTION * _SAMPLE_RATE_HZ:
            sys.stderr.write(
                f"WARNING: stream rate {rate:.0f} Hz is "
                f"{100.0 * rate / _SAMPLE_RATE_HZ:.1f} % of {_SAMPLE_RATE_HZ} Hz "
                f"({n_total} samples in {wall:.2f} s): samples were lost without "
                "being counted; do not rely on the duration or the charge of this capture.\n"
            )
        sys.stderr.flush()

        if stop_requested.flag:
            # 130 is the standard Bash SIGINT exit code. The output is
            # completed as the block unwinds: shorter, but valid.
            raise typer.Exit(code=130)
        if n_total == 0:
            sys.stderr.write(
                "error: no samples captured: check the PPK2 mode and the DUT's power\n"
            )
            sys.stderr.flush()
            raise typer.Exit(code=1)
        if n_total < target:
            # The clock ended it: the file is kept, and is not what was asked for.
            sys.stderr.write(
                f"error: capture ended with {n_total} of {target} samples: "
                "the PPK2 stopped sending, or the computer did not keep up\n"
            )
            sys.stderr.flush()
            raise typer.Exit(code=1)


def parse_user_gain_spec(spec: str) -> tuple[int, float]:
    """Parse one ``--user-gain RANGE:GAIN`` token into ``(range_idx, gain)``.

    Raises:
        typer.BadParameter: If it is not ``RANGE:GAIN``, the range is not
            0-4, or the gain is not from 0.9 to 1.1.
    """
    label = "--user-gain"
    parts = spec.split(":")
    if len(parts) != 2:
        raise typer.BadParameter(
            f"{label} expects RANGE:GAIN (got '{spec}'); example: --user-gain 2:1.05",
            param_hint=label,
        )
    range_str, gain_str = parts[0].strip(), parts[1].strip()
    try:
        range_idx = int(range_str)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{label} range must be an integer from 0 to 4 (got '{range_str}')",
            param_hint=label,
        ) from exc
    if not 0 <= range_idx <= 4:
        raise typer.BadParameter(
            f"{label} range must be from 0 to 4 (got {range_idx})",
            param_hint=label,
        )
    try:
        gain = float(gain_str)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{label} gain must be a float (got '{gain_str}')",
            param_hint=label,
        ) from exc
    # The range of Nordic's app. NaN fails the comparison too.
    if not USER_GAIN_MIN <= gain <= USER_GAIN_MAX:
        raise typer.BadParameter(
            f"{label} gain must be from {USER_GAIN_MIN} to {USER_GAIN_MAX} (got '{gain_str}')",
            param_hint=label,
        )
    return range_idx, gain


# What `signal.signal` returns: SIG_DFL / SIG_IGN or a Python callable.
_SignalHandler = Callable[[int, FrameType | None], object] | int | None


class _SigintFlag:
    """A SIGINT handler that sets ``flag``; the previous handler comes back on exit."""

    def __init__(self) -> None:
        self.flag = False
        self._prev: _SignalHandler = signal.SIG_DFL

    def __enter__(self) -> "_SigintFlag":
        def _handler(_signum: int, _frame: FrameType | None) -> None:
            self.flag = True

        self._prev = signal.signal(signal.SIGINT, _handler)
        return self

    def __exit__(self, *_args: object) -> None:
        signal.signal(signal.SIGINT, self._prev)
