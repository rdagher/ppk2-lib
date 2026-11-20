"""``ppk2 power on|off``: switch power to the DUT, optionally holding it on."""

import signal
import sys
from enum import StrEnum

from ppk2 import Mode, Session
from ppk2.cli.commands import resolve_device
from ppk2.cli.csv import vdd_to_mv
from ppk2.cli.signals import signals_to_systemexit


class PowerState(StrEnum):
    """``on`` / ``off`` argument shape for ``ppk2 power``."""

    ON = "on"
    OFF = "off"


def power(
    serial: str | None,
    port: str | None,
    state: PowerState,
    hold: bool,
    vdd: float,
    source: bool,
) -> None:
    """Open a session, switch the power, optionally block until SIGINT, then close."""
    device = resolve_device(serial, port)
    mv = vdd_to_mv(vdd)
    mode = Mode.SOURCE if source else Mode.AMPERE

    # SIGTERM/SIGHUP -> SystemExit so a kill still cuts the power and
    # closes the port on the way out.
    with signals_to_systemexit("SIGTERM", "SIGHUP"), Session.open(device) as session:
        session.set_mode(mode)
        session.set_source_voltage(mv)
        session.start_measuring()  # required so DEVICE_RUNNING_SET isn't dropped
        if state is PowerState.ON:
            session.power_on()
            if hold:
                _hold_until_sigint()
            # When `hold=False` the with-block's teardown runs power_off
            # implicitly when we leave the scope.
        else:
            session.power_off()


def _hold_until_sigint() -> None:
    """Block until SIGINT, then return so the caller can clean up."""
    received = False

    def _handler(_signum: int, _frame: object) -> None:
        nonlocal received
        received = True

    prev = signal.signal(signal.SIGINT, _handler)
    try:
        sys.stderr.write("ppk2: holding power on; Ctrl-C to release\n")
        sys.stderr.flush()
        signal.pause()  # blocks until any signal; our handler unblocks SIGINT
        if not received:
            # Unlikely (SIGINT is the only signal we registered) but defensive.
            sys.stderr.write("ppk2: woke from pause without SIGINT, exiting anyway\n")
    finally:
        signal.signal(signal.SIGINT, prev)
