"""``ppk2 capture`` — stream the current trace to a CSV file."""

import signal
import sys
from collections.abc import Callable, Iterable
from contextlib import suppress
from math import isnan
from pathlib import Path
from time import monotonic
from types import FrameType

import typer

from ppk2 import Mode, Sample, Session
from ppk2.cli.commands import resolve_device
from ppk2.cli.csv import CSV_HEADER, gui_noise_floor, vdd_to_mv, write_csv_row
from ppk2.cli.signals import signals_to_systemexit

# 100 kSPS — one sample every 10 µs = 0.01 ms.
_SAMPLE_RATE_HZ = 100_000
_SAMPLE_PERIOD_MS = 1000.0 / _SAMPLE_RATE_HZ  # = 0.01
_PROGRESS_INTERVAL_S = 1.0

#: Cumulative data-loss count at which we first emit a mid-stream
#: warning. Matches the Nordic GUI's ``DATALOSS_THRESHOLD``.
_DATALOSS_WARN_THRESHOLD = 500

#: Post-capture watchdog: a realized stream rate below this fraction of
#: 100 kSPS (on captures longer than 0.5 s) means the host lost
#: samples — energy/latency integrals over the CSV become unreliable.
_RATE_WATCHDOG_FRACTION = 0.95


def capture(
    serial: str | None,
    port: str | None,
    out: Path,
    seconds: float,
    vdd: float,
    source: bool,
    user_gain_specs: Iterable[str] = (),
) -> None:
    """Run the session setup, stream samples for ``seconds``, write 11-column CSV."""
    # Parse user-gain specs FIRST so malformed flags surface as a
    # BadParameter at CLI parse-time rather than after a (potentially
    # slow) hardware discovery step.
    user_gains = [parse_user_gain_spec(spec) for spec in user_gain_specs]
    device = resolve_device(serial, port)
    mv = vdd_to_mv(vdd)
    mode = Mode.SOURCE if source else Mode.AMPERE

    sys.stderr.write(f"opening session (mode={mode.name}, vdd={mv} mV)\n")
    if user_gains:
        gains_repr = ", ".join(f"r{r}={g:.4f}" for r, g in user_gains)
        sys.stderr.write(f"  user-gain overrides: {gains_repr}\n")
    sys.stderr.write(f"capturing {seconds:.2f} s -> {out} (Ctrl-C to stop early)\n")
    sys.stderr.flush()

    # Ensure the parent dir exists; users typically pass a bare filename.
    out.parent.mkdir(parents=True, exist_ok=True)

    stop_requested = _SigintFlag()

    # SIGTERM/SIGHUP raise SystemExit inside this block, so a `kill`
    # or closed terminal unwinds the with-stack like a Ctrl-C would:
    # the session tears down (FET open, port closed) and the CSV is
    # flushed on close.
    with (
        out.open("w", encoding="utf-8") as csv_out,
        stop_requested,
        signals_to_systemexit("SIGTERM", "SIGHUP"),
    ):
        csv_out.write(f"{CSV_HEADER}\n")

        with Session.open(device) as session:
            session.set_mode(mode)
            session.set_source_voltage(mv)
            for range_idx, gain in user_gains:
                session.set_user_gain(range_idx, gain)
            session.start_measuring()
            # latch_s=0: the capture loop's own reads finish the FET
            # latch, so t=0 ≈ FET-on and the DUT's boot inrush lands
            # in the trace instead of being drained away.
            session.power_on(latch_s=0.0)

            n_samples = 0
            n_dataloss = 0  # NaN placeholders from the stream parser's data-loss path
            sum_ua = 0.0
            t_ms = 0.0
            last_progress = monotonic()
            started = monotonic()
            deadline = started + seconds
            dataloss_warned = False

            def on_dataloss(total: int) -> None:
                nonlocal dataloss_warned
                if dataloss_warned or total < _DATALOSS_WARN_THRESHOLD:
                    return
                dataloss_warned = True
                sys.stderr.write(
                    f"  warning: data loss detected at sample ~{n_samples + n_dataloss}; "
                    f"{total} placeholders so far. Likely cause: USB cable / hub / host "
                    "contention. Capture continues; placeholders are skipped from CSV.\n"
                )
                sys.stderr.flush()

            def emit(s: Sample) -> bool:
                nonlocal n_samples, n_dataloss, sum_ua, t_ms, last_progress
                if stop_requested.flag:
                    return False
                # NaN samples are data-loss placeholders. Advance the
                # timeline so the next real sample's timestamp is right,
                # but don't write a row (matching the Nordic GUI's
                # export behavior) and don't pollute the running mean
                # with NaN. Real values pass through the GUI's 0.2 µA
                # noise-floor clamp before both the row and the stats.
                ua = gui_noise_floor(s.current_micro_amps)
                if isnan(ua):
                    n_dataloss += 1
                else:
                    write_csv_row(csv_out, t_ms, ua, s.logic)
                    n_samples += 1
                    sum_ua += ua
                t_ms += _SAMPLE_PERIOD_MS

                now = monotonic()
                if now - last_progress >= _PROGRESS_INTERVAL_S:
                    mean = sum_ua / n_samples if n_samples else 0.0
                    elapsed = now - started
                    sys.stderr.write(
                        f"  [{elapsed:5.1f}s]  {n_samples:>10} samples  mean {mean:>7.2f} µA\n"
                    )
                    sys.stderr.flush()
                    last_progress = now

                return monotonic() < deadline

            # One-shot: drop the bytes that piled up between FET-on
            # and here, so the first CSV row is ≈ now ≈ FET-on.
            session.drop_pending_backlog()
            session.capture(emit, on_dataloss=on_dataloss)

            with suppress(Exception):
                session.power_off()
            with suppress(Exception):
                session.stop_measuring()

        wall = monotonic() - started
        # Placeholders occupy timeline slots, so the realized stream
        # rate counts them; the dataloss warning below accounts for
        # any gap between rows written and samples streamed.
        n_total = n_samples + n_dataloss
        rate = n_total / wall if wall > 0 else 0.0
        if stop_requested.flag:
            sys.stderr.write("interrupted — CSV flushed\n")
        suffix = " — stopped by SIGINT" if stop_requested.flag else ""
        sys.stderr.write(
            f"captured {n_samples} samples over {wall:.2f} s ({rate:.0f} Hz){suffix}\n"
        )
        if n_dataloss > 0:
            sys.stderr.write(
                f"  warning: {n_dataloss} data-loss placeholder samples "
                f"({100.0 * n_dataloss / n_total:.3f} % of stream) "
                "skipped from CSV\n"
            )
        if wall > 0.5 and n_total > 0 and rate < _RATE_WATCHDOG_FRACTION * _SAMPLE_RATE_HZ:
            sys.stderr.write(
                f"WARNING: stream rate {rate:.0f} Hz is "
                f"{100.0 * rate / _SAMPLE_RATE_HZ:.1f}% of {_SAMPLE_RATE_HZ} Hz "
                f"({n_total} samples in {wall:.2f} s) — samples dropped; "
                "energy/latency integrals may be unreliable.\n"
            )
        sys.stderr.flush()

        if stop_requested.flag:
            # 130 is the standard Bash SIGINT exit code. The CSV was
            # flushed on the with-block unwind — a shorter valid CSV.
            raise typer.Exit(code=130)
        if n_total == 0:
            sys.stderr.write("no samples captured — check PPK2 mode + DUT power\n")
            sys.stderr.flush()
            raise typer.Exit(code=1)


def parse_user_gain_spec(spec: str) -> tuple[int, float]:
    """Parse a ``RANGE:GAIN`` token from ``--user-gain`` into ``(range_idx, gain)``.

    Accepts the form documented in ``ppk2 capture --help``: a 0..=4
    range index, a literal ``:`` separator, and a float gain. Whitespace
    around either component is tolerated (Typer strips outer whitespace
    already, but explicit ``" 2 : 1.05 "`` should still work).

    Args:
        spec: One token from a repeatable ``--user-gain`` option.

    Returns:
        ``(range_idx, gain)``. ``range_idx`` is in ``0..=4``; ``gain``
        is a finite float.

    Raises:
        typer.BadParameter: If the token doesn't match ``RANGE:GAIN``
            shape, the range is out of band, or the gain isn't a finite
            float. The message names ``--user-gain`` and the offending
            token verbatim so the user can find it.
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
            f"{label} range must be an integer 0..=4 (got '{range_str}')",
            param_hint=label,
        ) from exc
    if not 0 <= range_idx <= 4:
        raise typer.BadParameter(
            f"{label} range must be 0..=4 (got {range_idx})",
            param_hint=label,
        )
    try:
        gain = float(gain_str)
    except ValueError as exc:
        raise typer.BadParameter(
            f"{label} gain must be a float (got '{gain_str}')",
            param_hint=label,
        ) from exc
    # Reject NaN / ±inf — they pass float() but would poison the
    # host-side calibration math (set_user_gain is host-side only).
    if gain != gain or gain in (float("inf"), float("-inf")):
        raise typer.BadParameter(
            f"{label} gain must be finite (got '{gain_str}')",
            param_hint=label,
        )
    return range_idx, gain


# Matches `signal.signal`'s return type: either the SIG_DFL / SIG_IGN
# sentinels or a Python callable.
_SignalHandler = Callable[[int, FrameType | None], object] | int | None


class _SigintFlag:
    """Installs a SIGINT handler that flips ``flag`` once; restores on exit.

    Used as a context manager so the previous handler is restored if the
    capture loop throws.
    """

    def __init__(self) -> None:
        """Start with flag clear; no handler installed yet."""
        self.flag = False
        self._prev: _SignalHandler = signal.SIG_DFL

    def __enter__(self) -> "_SigintFlag":
        """Install the SIGINT handler that sets ``flag``."""

        def _handler(_signum: int, _frame: FrameType | None) -> None:
            self.flag = True

        self._prev = signal.signal(signal.SIGINT, _handler)
        return self

    def __exit__(self, *_args: object) -> None:
        """Restore the previously installed SIGINT handler."""
        signal.signal(signal.SIGINT, self._prev)
